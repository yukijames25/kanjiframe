"""A COBOL copybook parser for record layouts (the subset found in data-definition copybooks).

Supported: levels 01-49 (66/88 skipped), FILLER, PIC/PICTURE with repeat counts, X/A, N/G (double-byte),
9/S/V/P numerics, numeric-edited pictures (read as text), USAGE DISPLAY / DISPLAY-1 / COMP / COMP-4 /
COMP-5 / BINARY / COMP-3 / PACKED-DECIMAL, OCCURS n [TIMES] (and OCCURS m TO n DEPENDING ON: the maximum is
laid out), REDEFINES, SIGN LEADING/TRAILING [SEPARATE], fixed-format columns (1-6 sequence, 7 indicator,
73-80 ignored) and free format with *> comments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .numbers import binary_length


class CopybookError(ValueError):
    pass


USAGE_WORDS = {
    "DISPLAY": "display", "DISPLAY-1": "display-1", "NATIONAL": "display-1",
    "COMP": "binary", "COMPUTATIONAL": "binary", "COMP-4": "binary", "COMPUTATIONAL-4": "binary",
    "COMP-5": "binary", "COMPUTATIONAL-5": "binary", "BINARY": "binary",
    "COMP-3": "packed", "COMPUTATIONAL-3": "packed", "PACKED-DECIMAL": "packed",
    "COMP-1": "float", "COMP-2": "float", "COMPUTATIONAL-1": "float", "COMPUTATIONAL-2": "float",
    "INDEX": "index", "POINTER": "pointer",
}
KEYWORDS = set(USAGE_WORDS) | {"PIC", "PICTURE", "USAGE", "OCCURS", "REDEFINES", "VALUE", "VALUES", "SIGN",
                                "SYNC", "SYNCHRONIZED", "JUSTIFIED", "JUST", "BLANK", "IS", "EXTERNAL", "GLOBAL"}


@dataclass
class Item:
    level: int
    name: str
    pic: str | None = None
    usage: str | None = None
    occurs: int = 1
    depending_on: str | None = None
    redefines: str | None = None
    sign_separate: bool = False
    sign_leading: bool = False
    children: list = field(default_factory=list)
    line: int = 0
    # computed
    kind: str = "group"  # group | text | dbcs | zoned | packed | binary
    size: int = 0  # bytes of one occurrence
    offset: int = 0  # of the first occurrence, from the start of the record
    digits: int = 0
    scale: int = 0
    signed: bool = False

    @property
    def is_group(self) -> bool:
        return not self.pic

    def to_dict(self) -> dict:
        d = {"level": self.level, "name": self.name, "offset": self.offset, "size": self.size, "kind": self.kind}
        if self.pic:
            d["pic"] = self.pic
        if self.occurs > 1:
            d["occurs"] = self.occurs
        if self.redefines:
            d["redefines"] = self.redefines
        if self.kind in ("zoned", "packed", "binary"):
            d.update(digits=self.digits, scale=self.scale, signed=self.signed)
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


def _clean(text: str) -> list[tuple[int, str]]:
    lines = text.replace("\t", "    ").splitlines()
    fixed = sum(1 for ln in lines if len(ln) > 7 and (ln[:6].strip() == "" or ln[:6].strip().isdigit())) > len(
        [ln for ln in lines if ln.strip()]) * 0.6 and any(len(ln) > 6 and ln[6] in " *-/" for ln in lines)
    out = []
    for no, ln in enumerate(lines, 1):
        if fixed:
            if len(ln) > 6 and ln[6] in "*/":
                continue
            ln = ln[7:72] if len(ln) > 6 else ""
        ln = ln.split("*>")[0]
        if ln.strip():
            out.append((no, ln))
    return out


def _expand(pic: str) -> str:
    return re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), pic.upper())


def parse(text: str) -> list[Item]:
    """Parse copybook text into a list of 01-level (or top-level) items with offsets computed."""
    stmts: list[tuple[int, str]] = []
    buf, start = [], None
    for no, ln in _clean(text):
        ln = re.sub(r"'[^']*'|\"[^\"]*\"", "LIT", ln)  # VALUE literals may contain dots and spaces
        for piece in re.split(r"(\.(?=\s|$))", ln):
            if piece == ".":
                if buf:
                    stmts.append((start, " ".join(buf)))
                buf, start = [], None
            elif piece.strip():
                if start is None:
                    start = no
                buf.append(piece.strip())
    if buf:
        stmts.append((start, " ".join(buf)))

    items: list[Item] = []
    for no, st in stmts:
        toks = st.split()
        if not toks[0].isdigit():
            raise CopybookError(f"line {no}: expected a level number, got {toks[0]!r}")
        level = int(toks[0])
        if level in (66, 88):
            continue
        i = 1
        name = "FILLER"
        if i < len(toks) and toks[i].upper() not in KEYWORDS:
            name = toks[i]
            i += 1
        it = Item(level=level, name=name, line=no)
        while i < len(toks):
            w = toks[i].upper()
            if w in ("PIC", "PICTURE"):
                i += 1
                if i < len(toks) and toks[i].upper() == "IS":
                    i += 1
                it.pic = toks[i]
            elif w == "USAGE":
                i += 1
                if i < len(toks) and toks[i].upper() == "IS":
                    i += 1
                it.usage = USAGE_WORDS.get(toks[i].upper(), toks[i].lower())
            elif w in USAGE_WORDS:
                it.usage = USAGE_WORDS[w]
            elif w == "OCCURS":
                nums = [t for t in toks[i + 1:i + 6] if t.isdigit()]
                if not nums:
                    raise CopybookError(f"line {no}: OCCURS without a count")
                it.occurs = int(nums[1] if len(nums) > 1 and "TO" in [t.upper() for t in toks[i + 1:i + 5]] else nums[0])
                rest = [t.upper() for t in toks[i:]]
                if "DEPENDING" in rest:
                    k = rest.index("DEPENDING")
                    j = k + 1 + (1 if k + 1 < len(rest) and rest[k + 1] == "ON" else 0)
                    it.depending_on = toks[i + j] if i + j < len(toks) else None
            elif w == "REDEFINES":
                i += 1
                it.redefines = toks[i]
            elif w == "SIGN":
                rest = [t.upper() for t in toks[i + 1:i + 5]]
                it.sign_leading = "LEADING" in rest
                it.sign_separate = "SEPARATE" in rest
            elif w in ("VALUE", "VALUES"):
                break  # the rest is the literal (already masked)
            i += 1
        items.append(it)

    roots: list[Item] = []
    stack: list[Item] = []
    for it in items:
        while stack and stack[-1].level >= it.level:
            stack.pop()
        if stack:
            stack[-1].children.append(it)
        else:
            roots.append(it)
        stack.append(it)
    for r in roots:
        _measure(r, None)
        _place(r, 0)
    return roots


def _measure(it: Item, inherited_usage: str | None) -> None:
    usage = it.usage or inherited_usage
    if it.children:
        for c in it.children:
            _measure(c, usage)
        by_name: dict[str, Item] = {}
        span: dict[int, int] = {}  # id(base child) -> bytes it occupies (the largest of it and its REDEFINES)
        for c in it.children:
            if c.redefines:
                base = by_name.get(c.redefines.upper())
                if base is None:
                    raise CopybookError(f"line {c.line}: REDEFINES {c.redefines} does not name an earlier item")
                span[id(base)] = max(span[id(base)], c.size * c.occurs)
                continue
            by_name[c.name.upper()] = c
            span[id(c)] = c.size * c.occurs
        it._span = span  # type: ignore[attr-defined]
        it.size = sum(span.values())
        it.kind = "group"
        return
    if not it.pic:
        raise CopybookError(f"line {it.line}: {it.name} has neither PIC nor subordinate items")
    p = _expand(it.pic)
    if usage == "float":
        raise CopybookError(f"line {it.line}: {it.name}: COMP-1/COMP-2 (floating point) is not supported")
    if set(p) <= set("NG") or usage == "display-1":
        it.kind, it.size = "dbcs", 2 * len(p.replace("N", "x").replace("G", "x"))
    elif set(p) <= set("XA"):
        it.kind, it.size = "text", len(p)
    elif set(p) <= set("S9VP"):
        it.signed = p.startswith("S")
        it.digits = p.count("9")
        it.scale = p.split("V", 1)[1].count("9") if "V" in p else 0
        if usage == "packed":
            it.kind, it.size = "packed", it.digits // 2 + 1
        elif usage == "binary":
            it.kind, it.size = "binary", binary_length(it.digits)
        else:
            it.kind, it.size = "zoned", it.digits + (1 if it.sign_separate else 0)
    else:
        it.kind, it.size = "text", len(p.replace("V", ""))  # numeric-edited: read as printed text


def _place(it: Item, offset: int) -> None:
    it.offset = offset
    if not it.children:
        return
    pos = offset
    by_name = {}
    for c in it.children:
        if c.redefines:
            _place(c, by_name[c.redefines.upper()].offset)
            continue
        by_name[c.name.upper()] = c
        _place(c, pos)
        pos += it._span[id(c)]  # type: ignore[attr-defined]


def record_length(roots: list[Item]) -> int:
    return max((r.size * r.occurs for r in roots), default=0)


def fields(item: Item, prefix: str = "", shift: int = 0):
    """Yield (path, absolute_offset, leaf Item) for every elementary field, expanding OCCURS.

    Offsets computed by parse() are for the first occurrence of every enclosing OCCURS;
    *shift* carries the extra distance of the occurrence being expanded.
    """
    reps = range(item.occurs) if item.occurs > 1 else [None]
    for k in reps:
        name = item.name if k is None else f"{item.name}({k + 1})"
        path = f"{prefix}.{name}" if prefix else name
        extra = shift + (k or 0) * item.size
        if item.children:
            for c in item.children:
                yield from fields(c, path, extra)
        else:
            yield path, item.offset + extra, item
