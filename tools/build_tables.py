"""Pack the JDK dumps (tools/GenTables.java -> local/*.tsv) into src/kanjiframe/data/*.bin.

    java tools/GenTables.java local
    python tools/build_tables.py local

Format (zlib-compressed, big-endian uint16):
  sbcs[256]                       0xFFFF = unmapped
  dbcs[191*191]  for 0x4040..0xFEFE  ((b1-0x40)*191 + (b2-0x40)), 0xFFFF = unmapped
  n, then n pairs (unicode, code)   encode table; code < 0x100 = single byte, else double byte
"""
import os
import struct
import sys
import zlib

src = sys.argv[1] if len(sys.argv) > 1 else "local"
dst = os.path.join(os.path.dirname(__file__), "..", "src", "kanjiframe", "data")
os.makedirs(dst, exist_ok=True)
for name in ("ibm930", "ibm939"):
    sbcs = [0xFFFF] * 256
    dbcs = [0xFFFF] * (191 * 191)
    enc = []
    with open(os.path.join(src, name + ".tsv"), encoding="ascii") as fh:
        for line in fh:
            kind, a, b = line.split()
            if kind == "S":
                sbcs[int(a, 16)] = int(b, 16)
            elif kind == "D":
                code = int(a, 16)
                dbcs[((code >> 8) - 0x40) * 191 + ((code & 0xFF) - 0x40)] = int(b, 16)
            else:
                enc.append((int(a, 16), int(b, 16)))
    raw = struct.pack(">256H", *sbcs) + struct.pack(f">{len(dbcs)}H", *dbcs)
    raw += struct.pack(">I", len(enc)) + b"".join(struct.pack(">HH", u, c) for u, c in enc)
    with open(os.path.join(dst, name + ".bin"), "wb") as fh:
        fh.write(zlib.compress(raw, 9))
    print(name, len(raw), "->", os.path.getsize(os.path.join(dst, name + ".bin")), "bytes")
