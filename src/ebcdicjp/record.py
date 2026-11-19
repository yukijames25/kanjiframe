"""Fixed-length (and RDW variable-length) mainframe records <-> nested JSON via a copybook layout."""
from __future__ import annotations

from decimal import Decimal

from .codec import decode_report, encode_report
from .copybook import Item, fields
from .numbers import NumberError, binary, pack, unbin, unpack, unzone, zone

EBCDIC_PLUS, EBCDIC_MINUS = 0x4E, 0x60


class RecordError(ValueError):
    pass


def _num_out(v: Decimal, scale: int):
    if scale == 0:
        return int(v)
    return f"{v:.{scale}f}"


def decode_field(raw: bytes, it: Item, codepage: str, keep_spaces: bool = False):
    """Return (value, [issue dict without path/offset]) for one elementary field."""
    issues = []
    if it.kind in ("text", "dbcs"):
        text, iss = decode_report(raw, codepage, dbcs_only=(it.kind == "dbcs"))
        issues += [{"kind": i.kind, "detail": i.detail, "at": i.offset} for i in iss]
        if not keep_spaces:
            text = text.rstrip(" 　")
        return text, issues
    if raw and (set(raw) == {0x40} or set(raw) == {0x00}):
        what = "spaces" if raw[0] == 0x40 else "low-values (00)"
        return None, [{"kind": "blank", "detail": f"numeric field is all {what}"}]
    try:
        if it.kind == "packed":
            v = unpack(raw, it.scale)
        elif it.kind == "binary":
            v = unbin(raw, it.scale, it.signed)
        elif it.sign_separate:
            sign_byte = raw[0] if it.sign_leading else raw[-1]
            body = raw[1:] if it.sign_leading else raw[:-1]
            if sign_byte not in (EBCDIC_PLUS, EBCDIC_MINUS):
                raise NumberError(f"separate sign byte {sign_byte:02X} is not + (4E) or - (60)")
            v = unzone(bytes(body[:-1]) + bytes([0xF0 | (body[-1] & 0xF)]), it.scale)
            if sign_byte == EBCDIC_MINUS:
                v = -v
        else:
            if it.sign_leading and it.signed:
                raw = bytes([0xF0 | (raw[0] & 0xF)]) + raw[1:-1] + bytes([(raw[0] & 0xF0) | (raw[-1] & 0xF)])
            v = unzone(raw, it.scale)
        if v < 0 and not it.signed:
            issues.append({"kind": "sign", "detail": "negative value in an unsigned field"})
        return _num_out(v, it.scale), issues
    except NumberError as e:
        return None, [{"kind": "bad-number", "detail": str(e)}]


def decode_record(data: bytes, root: Item, codepage: str = "ibm930", keep_spaces: bool = False,
                  include_filler: bool = False):
    """Decode one record. Returns (value, issues) where issues carry path, offset and the raw bytes."""
    issues: list[dict] = []
    if len(data) < root.size:
        issues.append({"path": root.name, "offset": len(data), "kind": "short",
                       "detail": f"record is {len(data)} bytes; the layout needs {root.size}"})
        data = data + b"\x40" * (root.size - len(data))

    def walk(it: Item, shift: int, path: str):
        def one(k):
            extra = shift + k * it.size
            if it.children:
                out = {}
                family: dict[str, list] = {}  # base name -> [(child, its issues)]
                for c in it.children:
                    if c.name.upper() == "FILLER" and not include_filler:
                        continue
                    mark = len(issues)
                    out[c.name] = walk(c, extra, f"{path}.{c.name}")
                    mine = issues[mark:]
                    del issues[mark:]
                    family.setdefault((c.redefines or c.name).upper(), []).append(mine)
                for members in family.values():
                    real = [[i for i in m if i["kind"] != "blank"] for m in members]
                    clean = len(members) > 1 and any(not r for r in real)
                    for m in members:
                        for i in m:
                            if clean and i["kind"] != "blank":
                                i["detail"] = f"{i['kind']}: {i['detail']} (another REDEFINES reading of these bytes is clean)"
                                i["kind"] = "alternative"
                            issues.append(i)
                return out
            off = it.offset + extra
            raw = data[off:off + it.size]
            value, iss = decode_field(raw, it, codepage, keep_spaces)
            for i in iss:
                at = off + i.pop("at", 0)
                issues.append({"path": path + (f"({k + 1})" if it.occurs > 1 else ""), "offset": at,
                               "bytes": raw.hex(" ").upper(), **i})
            return value
        if it.occurs > 1:
            return [one(k) for k in range(it.occurs)]
        return one(0)

    return walk(root, 0, root.name), issues


def blank_record(root: Item, codepage: str = "ibm930") -> bytearray:
    """A record with every field at its empty value: text spaces, numbers zero."""
    buf = bytearray(b"\x40" * root.size)
    for _path, off, it in fields(root):
        buf[off:off + it.size] = _encode_leaf(it, None, codepage)
    return buf


def _encode_leaf(it: Item, value, codepage: str) -> bytes:
    if it.kind == "text":
        data, iss = encode_report("" if value is None else str(value), codepage)
        bad = [i for i in iss if i.kind == "unencodable"]
        if bad:
            raise RecordError(bad[0].detail)
        if len(data) > it.size:
            raise RecordError(f"{value!r} takes {len(data)} bytes (with SO/SI); the field holds {it.size}")
        return data + b"\x40" * (it.size - len(data))
    if it.kind == "dbcs":
        data, iss = encode_report("" if value is None else str(value), codepage, dbcs_only=True)
        bad = [i for i in iss if i.kind == "unencodable"]
        if bad:
            raise RecordError(bad[0].detail)
        if len(data) > it.size:
            raise RecordError(f"{value!r} needs {len(data) // 2} double-byte characters; the field holds {it.size // 2}")
        return data + b"\x40\x40" * ((it.size - len(data)) // 2)
    v = 0 if value is None or value == "" else value
    try:
        if it.kind == "packed":
            return pack(v, it.size, it.scale, it.signed)
        if it.kind == "binary":
            return binary(v, it.size, it.scale, it.signed)
        if it.sign_separate:
            body = zone(abs(Decimal(str(v))), it.size - 1, it.scale, signed=False)
            sign = bytes([EBCDIC_MINUS if Decimal(str(v)) < 0 else EBCDIC_PLUS])
            return sign + body if it.sign_leading else body + sign
        out = zone(v, it.size, it.scale, it.signed)
        if it.sign_leading and it.signed:
            out = bytes([(out[-1] & 0xF0) | (out[0] & 0xF)]) + out[1:-1] + bytes([0xF0 | (out[-1] & 0xF)])
        return out
    except NumberError as e:
        raise RecordError(str(e)) from None


def encode_record(value: dict, root: Item, codepage: str = "ibm930") -> tuple[bytes, list[dict]]:
    """Build one record from nested JSON (same shape decode_record returns). Missing fields stay empty."""
    buf = blank_record(root, codepage)
    notes: list[dict] = []

    def walk(it: Item, v, shift: int, path: str):
        if it.occurs > 1:
            if v is None:
                return
            if not isinstance(v, list):
                raise RecordError(f"{path}: OCCURS {it.occurs} needs a list")
            if len(v) > it.occurs:
                raise RecordError(f"{path}: {len(v)} items; OCCURS allows {it.occurs}")
            for k, x in enumerate(v):
                one(it, x, shift + k * it.size, f"{path}({k + 1})")
        else:
            one(it, v, shift, path)

    def one(it: Item, v, extra: int, path: str):
        if v is None:
            return
        if it.children:
            if not isinstance(v, dict):
                raise RecordError(f"{path}: a group needs an object with its fields")
            names = {c.name.upper(): c for c in it.children if c.name.upper() != "FILLER"}
            unknown = [k for k in v if k.upper() not in names]
            if unknown:
                raise RecordError(f"{path}: unknown field(s) {unknown}; have {[c.name for c in it.children if c.name.upper() != 'FILLER']}")
            given = {k.upper() for k in v}
            for c in it.children:
                if c.redefines and c.name.upper() in given and c.redefines.upper() in given:
                    raise RecordError(f"{path}: give either {c.redefines} or {c.name} (REDEFINES), not both")
            for k, x in v.items():
                walk(names[k.upper()], x, extra, f"{path}.{names[k.upper()].name}")
            return
        off = it.offset + extra
        buf[off:off + it.size] = _encode_leaf(it, v, codepage)
        if it.kind in ("text", "dbcs"):
            _, iss = encode_report(str(v), codepage, dbcs_only=(it.kind == "dbcs"))
            notes.extend({"path": path, "kind": i.kind, "detail": i.detail} for i in iss if i.kind == "one-way")

    walk(root, value, 0, root.name)
    return bytes(buf), notes


def split_records(data: bytes, lrecl: int, rdw: bool = False):
    """Yield (index, offset, bytes). With rdw, each record starts with a 4-byte RDW (length incl. RDW)."""
    if rdw:
        pos, k = 0, 0
        while pos + 4 <= len(data):
            n = int.from_bytes(data[pos:pos + 2], "big")
            if n < 4:
                raise RecordError(f"record {k + 1} at byte {pos}: RDW length {n} is invalid")
            yield k, pos + 4, data[pos + 4:pos + n]
            pos += n
            k += 1
        return
    if lrecl <= 0:
        raise RecordError("record length must be positive")
    for k in range(0, (len(data) + lrecl - 1) // lrecl):
        yield k, k * lrecl, data[k * lrecl:(k + 1) * lrecl]
