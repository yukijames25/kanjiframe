"""Operations shared by the CLI and the MCP server."""
from __future__ import annotations

from .codec import decode_report
from .copybook import Item, fields, parse, record_length
from .record import decode_record, encode_record, split_records


def load_layout(copybook_text: str, record: str | None = None) -> Item:
    roots = parse(copybook_text)
    if not roots:
        raise ValueError("the copybook defines no record")
    if record:
        for r in roots:
            if r.name.upper() == record.upper():
                return r
        raise ValueError(f"record {record!r} not in the copybook (have {[r.name for r in roots]})")
    return roots[0]


def layout_rows(root: Item) -> list[dict]:
    rows = []
    for path, off, it in fields(root):
        rows.append({"path": path, "pos": off + 1, "offset": off, "length": it.size, "kind": it.kind,
                     "pic": it.pic, **({"scale": it.scale, "signed": it.signed} if it.kind in ("zoned", "packed", "binary") else {}),
                     **({"redefines": it.redefines} if it.redefines else {})})
    return rows


def read_records(data: bytes, root: Item, codepage: str = "ibm930", rdw: bool = False, lrecl: int | None = None,
                 skip: int = 0, limit: int | None = None, keep_spaces: bool = False, use: list | None = None) -> dict:
    lrecl = lrecl or root.size
    out = []
    notes = []
    total = 0
    if not rdw and lrecl and len(data) % lrecl:
        notes.append(f"file size {len(data)} is not a multiple of the record length {lrecl}: "
                     f"the last record is {len(data) % lrecl} bytes (wrong layout, RDW, or line breaks?)")
    if not rdw and lrecl != root.size:
        notes.append(f"record length {lrecl} differs from the copybook's {root.size} bytes")
    for k, off, raw in split_records(data, lrecl, rdw):
        total += 1
        if k < skip or (limit is not None and len(out) >= limit):
            continue
        value, issues = decode_record(raw, root, codepage, keep_spaces, use=use)
        out.append({"index": k + 1, "offset": off, "value": value, "issues": issues})
    return {"codepage": codepage, "record_length": lrecl, "records_in_file": total, "records": out, "notes": notes}


def write_records(records: list, root: Item, codepage: str = "ibm930", rdw: bool = False) -> tuple[bytes, list]:
    buf = bytearray()
    notes = []
    for k, rec in enumerate(records, 1):
        data, n = encode_record(rec, root, codepage)
        notes += [dict(x, record=k) for x in n]
        if rdw:
            buf += (len(data) + 4).to_bytes(2, "big") + b"\x00\x00"
        buf += data
    return bytes(buf), notes


def detect_codepage(data: bytes, root: Item | None = None, sample: int = 200_000) -> dict:
    """Guess IBM930 vs IBM939 from undecodable bytes; say 'ambiguous' (with both readings) when it can't tell."""
    data = data[:sample]
    result = {}
    for cp in ("ibm930", "ibm939"):
        if root is not None:
            bad = 0
            texts = []
            for _k, _o, raw in split_records(data, root.size):
                _, issues = decode_record(raw, root, cp)
                bad += sum(1 for i in issues if i["kind"] in ("unmapped", "odd-dbcs", "bad-shift"))
                if len(texts) < 3:
                    texts.append(raw)
            preview = " / ".join(decode_report(t, cp)[0][:40] for t in texts)
        else:
            text, issues = decode_report(data, cp)
            bad = sum(1 for i in issues if i.kind in ("unmapped", "odd-dbcs", "bad-shift"))
            preview = text[:80]
        letters = [ch for ch in decode_report(data, cp)[0] if "a" <= ch <= "z"]
        vowels = sum(1 for ch in letters if ch in "aeiou")
        result[cp] = {"problems": bad, "lowercase_letters": len(letters),
                      "vowel_ratio": round(vowels / len(letters), 2) if letters else None, "preview": preview}
    a, b = result["ibm930"]["problems"], result["ibm939"]["problems"]
    lower = result["ibm939"]["lowercase_letters"]
    ratio = result["ibm939"]["vowel_ratio"]
    if a != b:
        guess = "ibm930" if a < b else "ibm939"
        why = f"{guess} decodes with fewer problems ({min(a, b)} vs {max(a, b)})"
    elif lower >= 8 and ratio is not None and ratio < 0.25:
        # half-width katakana bytes read as IBM939 lowercase give consonant soup ("zuj...")
        guess, why = "ibm930", (f"IBM939 would read {lower} bytes as lowercase letters with only {ratio:.0%} vowels — "
                                "they look like half-width katakana, so IBM930")
    elif lower >= 8 and ratio is not None and ratio >= 0.3:
        guess, why = "ibm939", f"IBM939 reads {lower} bytes as lowercase text with {ratio:.0%} vowels, like real words"
    elif lower and not a:
        guess, why = "ambiguous", ("both decode cleanly; IBM939 reads some bytes as lowercase letters where IBM930 reads "
                                   "half-width katakana — compare the previews")
    else:
        guess, why = "ambiguous", "both decode the same way here; compare the previews"
    return {"guess": guess, "why": why, "candidates": result}


def text_preview(data: bytes, codepage: str) -> dict:
    text, issues = decode_report(data, codepage)
    return {"text": text, "issues": [i.to_dict() for i in issues]}


__all__ = ["load_layout", "layout_rows", "read_records", "write_records", "detect_codepage", "text_preview",
           "record_length"]
