"""Operations shared by the CLI and the MCP server."""
from __future__ import annotations

from .codec import decode_report
from .copybook import Item, fields, parse, record_length
from .record import RecordError, decode_record, encode_record, split_records


def read_copybook(raw: bytes, encoding: str | None = "auto") -> tuple[str, str, str | None]:
    """Decode copybook bytes. "auto": UTF-8 if valid, else Shift_JIS (cp932), which is what most sites keep."""
    if encoding and encoding.lower() != "auto":
        return raw.decode(encoding), encoding, None
    try:
        return raw.decode("utf-8-sig"), "utf-8", None
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp932"), "cp932", "copybook is not UTF-8; read it as Shift_JIS (cp932)"
    except UnicodeDecodeError as e:
        raise ValueError(f"copybook is neither UTF-8 nor Shift_JIS (byte {e.start + 1}); "
                         "give its encoding with --copybook-encoding") from None


def rdw_records(data: bytes) -> int | None:
    """Number of records if *data* is exactly a chain of RDW records (length incl. RDW, then two zero bytes)."""
    pos = k = 0
    while pos < len(data):
        if pos + 4 > len(data) or data[pos + 2:pos + 4] != b"\x00\x00":
            return None
        n = int.from_bytes(data[pos:pos + 2], "big")
        if n <= 4:
            return None
        pos += n
        k += 1
    return k if pos == len(data) and k else None


def resolve(data: bytes, root: Item, codepage: str | None = "auto", rdw: bool | None = None,
            lrecl: int | None = None) -> dict:
    """Settle record framing and code page, saying what was assumed so the user can override it."""
    notes = []
    uncertain = False
    if rdw is None:
        n = rdw_records(data)
        size = lrecl or root.size
        if n is not None:
            rdw = True
            notes.append(f"assumed RDW variable-length records ({n} records): each starts with a 4-byte length; "
                         "use --no-rdw if that is wrong")
        else:
            rdw = False
            if size and len(data) % size:
                notes.append(f"file size {len(data)} is not a multiple of the record length {size}, and it is not an "
                             "RDW chain either: check the copybook, --lrecl, or line breaks added in transfer")
    elif not rdw and (lrecl or root.size) and len(data) % (lrecl or root.size):
        hint = " — it looks like RDW records: try --rdw" if rdw_records(data) else " (wrong layout, RDW, or line breaks?)"
        notes.append(f"file size {len(data)} is not a multiple of the record length {lrecl or root.size}: "
                     f"the last record is {len(data) % (lrecl or root.size)} bytes{hint}")
    if not codepage or codepage == "auto":
        d = detect_codepage(data, root, rdw=rdw, lrecl=lrecl)
        if d["guess"] == "ambiguous":
            codepage = "ibm930"
            if d["same_reading"]:
                notes.append("code page: IBM930 and IBM939 read this data the same way; read as IBM930")
            else:
                uncertain = True
                notes.append(f"code page UNCERTAIN: {d['why']}. Read as IBM930; if kana or lowercase look wrong, "
                             "rerun with --codepage ibm939 (`detect` shows both readings)")
        else:
            codepage = d["guess"]
            notes.append(f"code page: {codepage.upper()} ({d['why']}); use --codepage to override")
    return {"codepage": codepage, "rdw": rdw, "notes": notes, "codepage_uncertain": uncertain}


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


def read_records(data: bytes, root: Item, codepage: str = "auto", rdw: bool | None = None, lrecl: int | None = None,
                 skip: int = 0, limit: int | None = None, keep_spaces: bool = False, use: list | None = None) -> dict:
    """Decode records. codepage "auto" and rdw None are detected, and what was assumed is put in "notes"."""
    r = resolve(data, root, codepage, rdw, lrecl)
    codepage, rdw, notes = r["codepage"], r["rdw"], r["notes"]
    lrecl = lrecl or root.size
    out = []
    total = 0
    if not rdw and lrecl != root.size:
        notes.append(f"record length {lrecl} differs from the copybook's {root.size} bytes")
    for k, off, raw in split_records(data, lrecl, rdw):
        total += 1
        if k < skip or (limit is not None and len(out) >= limit):
            continue
        value, issues = decode_record(raw, root, codepage, keep_spaces, use=use)
        out.append({"index": k + 1, "offset": off, "value": value, "issues": issues})
    return {"codepage": codepage, "codepage_uncertain": r["codepage_uncertain"], "rdw": rdw, "record_length": lrecl, "records_in_file": total, "records": out,
            "notes": notes}


def write_records(records: list, root: Item, codepage: str = "ibm930", rdw: bool = False) -> tuple[bytes, list]:
    buf = bytearray()
    notes = []
    for k, rec in enumerate(records, 1):
        try:
            data, n = encode_record(rec, root, codepage)
        except RecordError as e:
            raise RecordError(f"record {k}: {e}") from None
        notes += [dict(x, record=k) for x in n]
        if rdw:
            buf += (len(data) + 4).to_bytes(2, "big") + b"\x00\x00"
        buf += data
    return bytes(buf), notes


HALF_KANA = range(0xFF61, 0xFFA0)


def _odd_mix(text: str) -> int:
    """Places where a lowercase letter touches a half-width kana ("tﾕnﾞ"): what a wrong kana code page produces."""
    n = 0
    for x, y in zip(text, text[1:]):
        lx, ly = "a" <= x <= "z", "a" <= y <= "z"
        kx, ky = ord(x) in HALF_KANA, ord(y) in HALF_KANA
        if (lx and ky) or (kx and ly):
            n += 1
    return n


def _field_texts(raw: bytes, root: Item, cp: str) -> list[str]:
    out = []
    for _p, off, it in fields(root):
        if it.kind in ("text", "dbcs"):
            out.append(decode_report(raw[off:off + it.size], cp, dbcs_only=it.kind == "dbcs", gaiji_mark="〓")[0].rstrip())
    return out


def _mix_example(preview: str) -> str:
    for word in preview.replace("|", " ").replace("/", " ").split():
        if _odd_mix(word):
            return repr(word)
    return "the preview"


def detect_codepage(data: bytes, root: Item | None = None, sample: int = 200_000, rdw: bool | None = None,
                    lrecl: int | None = None) -> dict:
    """Guess IBM930 vs IBM939; say 'ambiguous' (with both readings) when it can't tell.

    Signals, strongest first: bytes that do not decode; lowercase letters touching half-width kana
    (each code page reads the other's kana partly as lowercase); lowercase runs without vowels.
    "same_reading" is True when both code pages give the same text, so nothing depends on the choice.
    """
    if rdw is None:
        rdw = rdw_records(data) is not None
    records = [raw for _k, _o, raw in split_records(data, 0, True)] if rdw else None
    size = lrecl or (root.size if root is not None else 0)
    if records is None and root is not None:
        records = [raw for _k, _o, raw in split_records(data[:sample], size)]
    result = {}
    texts_by_cp = {}
    for cp in ("ibm930", "ibm939"):
        if root is not None:
            bad = 0
            texts: list[str] = []
            shown = []
            used = 0
            for raw in records:
                used += len(raw)
                if used > sample:
                    break
                _, issues = decode_record(raw, root, cp)
                bad += sum(1 for i in issues if i["kind"] in ("unmapped", "odd-dbcs", "bad-shift"))
                ft = _field_texts(raw, root, cp)
                texts += ft
                if len(shown) < 3:
                    shown.append(" | ".join(t for t in ft if t))
            preview = " / ".join(shown)
        else:
            body = b"".join(records) if records is not None else data
            text, issues = decode_report(body[:sample], cp)
            bad = sum(1 for i in issues if i.kind in ("unmapped", "odd-dbcs", "bad-shift"))
            texts = [text]
            preview = text[:80]
        joined = "\n".join(texts)
        texts_by_cp[cp] = joined
        letters = [ch for ch in joined if "a" <= ch <= "z"]
        vowels = sum(1 for ch in letters if ch in "aeiou")
        result[cp] = {"problems": bad, "lowercase_letters": len(letters), "mixed": _odd_mix(joined),
                      "vowel_ratio": round(vowels / len(letters), 2) if letters else None, "preview": preview}
    same = texts_by_cp["ibm930"] == texts_by_cp["ibm939"]
    a, b = result["ibm930"]["problems"], result["ibm939"]["problems"]
    ma, mb = result["ibm930"]["mixed"], result["ibm939"]["mixed"]
    lower = result["ibm939"]["lowercase_letters"]
    ratio = result["ibm939"]["vowel_ratio"]
    clear = abs(a - b) > max(2, max(a, b) // 10)  # numbers/binary bytes make noise in both; small gaps mean little
    if a != b and clear:
        guess = "ibm930" if a < b else "ibm939"
        why = f"{guess.upper()} decodes with fewer problems ({min(a, b)} vs {max(a, b)})"
    elif max(ma, mb) >= 2 and min(ma, mb) * 3 <= max(ma, mb):
        guess = "ibm930" if ma < mb else "ibm939"
        other = "ibm939" if guess == "ibm930" else "ibm930"
        why = (f"{other.upper()} would mix lowercase letters into half-width kana in {max(ma, mb)} places "
               f"(like {_mix_example(result[other]['preview'])}); {guess.upper()} in {min(ma, mb)}")
    elif lower >= 8 and ratio is not None and ratio < 0.25:
        # half-width katakana bytes read as IBM939 lowercase give consonant soup ("zuj...")
        guess, why = "ibm930", (f"IBM939 would read {lower} bytes as lowercase letters with only {ratio:.0%} vowels — "
                                "they look like half-width katakana, so IBM930")
    elif lower >= 8 and ratio is not None and ratio >= 0.3:
        guess, why = "ibm939", (f"IBM939 reads {lower} bytes as lowercase text with {ratio:.0%} vowels, like real words "
                                "(IBM930 would read them as half-width kana)")
    elif a != b:
        guess = "ibm930" if a < b else "ibm939"
        why = f"{guess.upper()} decodes with slightly fewer problems ({min(a, b)} vs {max(a, b)})"
    elif same:
        guess, why = "ambiguous", "both read this data the same way, so either is fine"
    else:
        guess, why = "ambiguous", ("IBM930 and IBM939 read some of this data differently (kana or lowercase) and "
                                   "nothing decides between them — compare the previews")
    return {"guess": guess, "why": why, "same_reading": same, "candidates": result}


def text_preview(data: bytes, codepage: str) -> dict:
    text, issues = decode_report(data, codepage)
    return {"text": text, "issues": [i.to_dict() for i in issues]}


__all__ = ["read_copybook", "rdw_records", "resolve", "load_layout", "layout_rows", "read_records", "write_records", "detect_codepage", "text_preview",
           "record_length"]
