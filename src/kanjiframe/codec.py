"""Decode / encode Japanese EBCDIC (IBM930, IBM939).

Mixed data (PIC X): single-byte EBCDIC, with double-byte runs between SO (0x0E) and SI (0x0F).
Graphic data (PIC N / G): double-byte only, no shift codes.

``errors`` works like Python's codecs: "strict" raises, "replace" puts U+FFFD / the
substitution byte, "ignore" drops. ``decode_report`` / ``encode_report`` never raise and
return the list of problems with byte / character offsets, which is what a person checking
migrated data needs.
"""
from __future__ import annotations

import codecs
from dataclasses import dataclass

from .tables import SI, SO, UNMAPPED, canonical, load

DBCS_SPACE = b"\x40\x40"
SUB_SBCS = b"\x3f"  # EBCDIC SUB
SUB_DBCS = b"\xfe\xfe"


@dataclass
class Issue:
    offset: int  # byte offset (decode) or character offset (encode)
    kind: str  # unmapped | bad-shift | odd-dbcs | unencodable | one-way
    detail: str

    def to_dict(self) -> dict:
        return {"offset": self.offset, "kind": self.kind, "detail": self.detail}


GETA = "〓"  # 〓: the conventional stand-in for a character that cannot be shown


def is_gaiji(cp: int) -> bool:
    """IBM user-defined area (6941-7FFE) decodes to the Unicode private-use area."""
    return 0xE000 <= cp <= 0xF8FF


def decode_report(data: bytes, codepage: str = "ibm930", dbcs_only: bool = False,
                  gaiji_mark: str | None = None) -> tuple[str, list[Issue]]:
    """Decode without raising; unmapped bytes become U+FFFD and are listed.

    外字 (user-defined characters) decode to private-use code points and are always listed as
    "gaiji"; with *gaiji_mark* (e.g. "〓") they are also shown as that mark instead of an invisible character.
    """
    t = load(codepage)
    out: list[str] = []
    so_at = None
    issues: list[Issue] = []
    double = dbcs_only
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if not dbcs_only and b == SO:
            if double:
                issues.append(Issue(i, "bad-shift", "SO while already in double-byte mode"))
            double = True
            so_at = i
            i += 1
            continue
        if not dbcs_only and b == SI:
            if not double:
                issues.append(Issue(i, "bad-shift", "SI without a preceding SO"))
            double = False
            i += 1
            continue
        if double:
            if i + 1 >= n or (not dbcs_only and data[i + 1] in (SO, SI)):
                if not (i + 1 >= n and not dbcs_only):  # at the end of mixed data this is the missing SI, reported below
                    issues.append(Issue(i, "odd-dbcs", f"lone byte {b:02X} in double-byte mode"))
                out.append("�")
                i += 1
                continue
            code = (b << 8) | data[i + 1]
            cp = t.dbcs.get(code)
            if cp is None:
                issues.append(Issue(i, "unmapped", f"double-byte {code:04X} has no character in {t.name}"))
                out.append("�")
            elif is_gaiji(cp):
                issues.append(Issue(i, "gaiji", f"user-defined character (外字) {code:04X}: needs the site's 外字 table"))
                out.append(gaiji_mark or chr(cp))
            else:
                out.append(chr(cp))
            i += 2
        else:
            cp = t.sbcs[b]
            if cp == UNMAPPED:
                issues.append(Issue(i, "unmapped", f"byte {b:02X} has no character in {t.name}"))
                out.append("�")
            else:
                out.append(chr(cp))
            i += 1
    if double and not dbcs_only:
        at = so_at if so_at is not None else n
        issues.append(Issue(at, "bad-shift", "the double-byte run started here has no SI before the field ends (missing SI)"))
    return "".join(out), issues


def encode_report(text: str, codepage: str = "ibm930", dbcs_only: bool = False,
                  shift_at_end: bool = True) -> tuple[bytes, list[Issue]]:
    """Encode without raising; characters that cannot be encoded get the substitution code.

    One-way characters (e.g. 〜 U+301C, which decodes back as ～ U+FF5E) are encoded and
    reported, because the value will not survive a round trip unchanged.
    """
    t = load(codepage)
    out = bytearray()
    issues: list[Issue] = []
    double = False
    for i, ch in enumerate(text):
        cp = ord(ch)
        hit = t.encode.get(cp) if cp <= 0xFFFF else None
        if hit is not None and dbcs_only and not hit[1]:
            hit = _single_to_double(t, cp)
        if hit is None:
            issues.append(Issue(i, "unencodable", f"{ch!r} (U+{cp:04X}) has no code in {t.name}"))
            hit = (SUB_DBCS, True) if (dbcs_only or double) else (SUB_SBCS, False)
        code, is_double = hit
        if cp in t.one_way:
            issues.append(Issue(i, "one-way", f"{ch!r} (U+{cp:04X}) is stored as {code.hex().upper()}, "
                                              f"which reads back as {chr(t.one_way[cp])!r} (U+{t.one_way[cp]:04X})"))
        if not dbcs_only and is_double != double:
            out.append(SO if is_double else SI)
            double = is_double
        out += code
    if double and shift_at_end and not dbcs_only:
        out.append(SI)
    return bytes(out), issues


def _single_to_double(t, cp: int):
    """In a PIC N field, a half-width character has to be stored as its full-width form."""
    if cp == 0x20:
        return (DBCS_SPACE, True)
    if 0x21 <= cp <= 0x7E:
        hit = t.encode.get(cp - 0x21 + 0xFF01)
        if hit and hit[1]:
            return hit
    return None


def decode(data: bytes, codepage: str = "ibm930", errors: str = "strict", dbcs_only: bool = False) -> str:
    text, issues = decode_report(data, codepage, dbcs_only)
    issues = [x for x in issues if x.kind != "gaiji"]  # 外字 decode losslessly to private-use code points
    if issues and errors == "strict":
        raise UnicodeDecodeError(canonical(codepage) or codepage, bytes(data), issues[0].offset,
                                 min(issues[0].offset + 1, len(data)) or 1, issues[0].detail)
    if errors == "ignore":
        text = text.replace("�", "")
    return text


def encode(text: str, codepage: str = "ibm930", errors: str = "strict", dbcs_only: bool = False) -> bytes:
    data, issues = encode_report(text, codepage, dbcs_only)
    bad = [x for x in issues if x.kind == "unencodable"]
    if bad and errors == "strict":
        raise UnicodeEncodeError(canonical(codepage) or codepage, text, bad[0].offset, bad[0].offset + 1, bad[0].detail)
    if bad and errors == "ignore":
        keep = "".join(ch for i, ch in enumerate(text) if i not in {x.offset for x in bad})
        data, _ = encode_report(keep, codepage, dbcs_only)
    return data


# ---- registration with Python's codecs: b"...".decode("ibm930") ------------------
def _search(name: str):
    key = canonical(name.replace("_", "-"))
    if key is None:
        return None

    def enc(s, errors="strict"):
        return encode(s, key, errors), len(s)

    def dec(b, errors="strict"):
        return decode(bytes(b), key, errors), len(b)

    return codecs.CodecInfo(enc, dec, name=key)


_registered = False


def register() -> None:
    global _registered
    if not _registered:
        codecs.register(_search)
        _registered = True
