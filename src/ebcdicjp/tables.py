"""IBM930 / IBM939 conversion tables, generated from the JDK charsets (see tools/)."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from importlib import resources

UNMAPPED = 0xFFFF
SO, SI = 0x0E, 0x0F

ALIASES = {
    "ibm930": "ibm930", "ibm-930": "ibm930", "cp930": "ibm930", "930": "ibm930", "ccsid930": "ibm930",
    "ibm939": "ibm939", "ibm-939": "ibm939", "cp939": "ibm939", "939": "ibm939", "ccsid939": "ibm939",
}


@dataclass
class Table:
    name: str
    sbcs: list  # byte -> code point (UNMAPPED if none)
    dbcs: dict  # 2-byte code -> code point
    encode: dict  # code point -> (bytes, is_double)
    one_way: dict = field(default_factory=dict)  # code point -> code point it comes back as

    def describe(self) -> str:
        return (f"{self.name}: {sum(1 for x in self.sbcs if x != UNMAPPED)} single-byte, "
                f"{len(self.dbcs)} double-byte, {len(self.one_way)} one-way characters")


_cache: dict[str, Table] = {}


def canonical(name: str) -> str | None:
    return ALIASES.get(name.strip().lower().replace("_", "-"))


def load(name: str) -> Table:
    key = canonical(name)
    if key is None:
        raise LookupError(f"unknown EBCDIC code page: {name!r} (have: ibm930, ibm939)")
    if key in _cache:
        return _cache[key]
    raw = zlib.decompress(resources.files("ebcdicjp").joinpath(f"data/{key}.bin").read_bytes())
    sbcs = list(struct.unpack_from(">256H", raw, 0))
    pos = 512
    flat = struct.unpack_from(f">{191 * 191}H", raw, pos)
    pos += 191 * 191 * 2
    dbcs = {}
    for i, cp in enumerate(flat):
        if cp != UNMAPPED:
            dbcs[((i // 191 + 0x40) << 8) | (i % 191 + 0x40)] = cp
    (n,) = struct.unpack_from(">I", raw, pos)
    pos += 4
    encode = {}
    one_way = {}
    for i in range(n):
        u, code = struct.unpack_from(">HH", raw, pos + i * 4)
        if code < 0x100:
            encode[u] = (bytes([code]), False)
            back = sbcs[code]
        else:
            encode[u] = (bytes([code >> 8, code & 0xFF]), True)
            back = dbcs.get(code, UNMAPPED)
        if back != u:
            one_way[u] = back
    t = Table(key, sbcs, dbcs, encode, one_way)
    _cache[key] = t
    return t
