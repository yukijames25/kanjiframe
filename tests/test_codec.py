"""Codec tests. The JDK's x-IBM930 / x-IBM939 are the reference: random strings must encode to the
same bytes, and random valid byte streams must decode to the same text (skipped if java is absent)."""
import os
import random
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import ebcdicjp  # noqa: E402
from ebcdicjp.tables import load  # noqa: E402

JAVA = shutil.which("java")


def oracle(mode: str, charset: str, lines: list[str]) -> list[str]:
    p = subprocess.run([JAVA, os.path.join(ROOT, "tools", "Oracle.java"), mode, charset],
                       input="\n".join(lines) + "\n", capture_output=True, text=True, encoding="ascii", timeout=300)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return p.stdout.splitlines()


def sample_strings(t, n: int, seed: int) -> list[str]:
    rnd = random.Random(seed)
    pools = [
        [chr(c) for c in range(0x20, 0x7F) if c in t.encode],                      # ASCII that exists
        [chr(c) for c in range(0xFF61, 0xFFA0) if c in t.encode],                  # half-width katakana
        [chr(cp) for code, cp in t.dbcs.items() if cp not in t.one_way][:20000],   # kanji / kana / symbols
    ]
    out = []
    for _ in range(n):
        s = []
        for _ in range(rnd.randint(0, 24)):
            s.append(rnd.choice(rnd.choice(pools)))
        out.append("".join(s))
    return out


class BasicTests(unittest.TestCase):
    def test_known_record(self):
        # bytes produced by the JDK for 「ﾔﾏﾀﾞ ﾀﾛｳ 山田太郎」 in IBM930
        data = bytes.fromhex("A9A491BE4091BB83400E4565456345AB456E0F")
        self.assertEqual(data.decode("ibm930"), "ﾔﾏﾀﾞ ﾀﾛｳ 山田太郎")
        self.assertEqual("ﾔﾏﾀﾞ ﾀﾛｳ 山田太郎".encode("cp930"), data)

    def test_930_vs_939_lowercase(self):
        # IBM930 has half-width katakana where IBM939 has a-z
        self.assertEqual(ebcdicjp.decode(b"\x81", "ibm939"), "a")
        self.assertNotEqual(ebcdicjp.decode(b"\x81", "ibm930"), "a")

    def test_report_lists_problems_with_offsets(self):
        text, issues = ebcdicjp.decode_report(b"\xc1\x0e\x45\x65\xc1", "ibm939")
        self.assertEqual([i.kind for i in issues], ["bad-shift"])  # the lone C1 at the end is the missing SI, reported once
        self.assertEqual(issues[0].offset, 1)  # pointed at the SO where the kanji run began
        with self.assertRaises(UnicodeDecodeError):
            b"\x0f".decode("ibm939")
        self.assertEqual(b"\x0f".decode("ibm939", "replace"), "")

    def test_one_way_characters_are_reported(self):
        data, issues = ebcdicjp.encode_report("〜", "ibm930")
        self.assertEqual(issues[0].kind, "one-way")
        self.assertEqual(ebcdicjp.decode(data, "ibm930"), "～")  # U+301C comes back as U+FF5E

    def test_unencodable(self):
        with self.assertRaises(UnicodeEncodeError):
            "😀".encode("ibm930")
        data, issues = ebcdicjp.encode_report("A😀", "ibm939")
        self.assertEqual(issues[0].kind, "unencodable")

    def test_dbcs_only_fields(self):
        data = ebcdicjp.encode("山田　A", "ibm939", dbcs_only=True)  # PIC N: no SO/SI, A becomes Ａ
        self.assertEqual(len(data), 8)
        self.assertNotIn(0x0E, data)
        self.assertEqual(ebcdicjp.decode(data, "ibm939", dbcs_only=True), "山田　Ａ")


@unittest.skipUnless(JAVA, "java not installed: reference comparison skipped")
class JdkReferenceTests(unittest.TestCase):
    def _check(self, codepage, charset, seed):
        t = load(codepage)
        strings = sample_strings(t, 600, seed)
        want = oracle("enc", charset, [" ".join(f"{ord(c):04X}" for c in s) for s in strings])
        for s, w in zip(strings, want):
            self.assertEqual(ebcdicjp.encode(s, codepage).hex().upper(), w, repr(s))
        got = oracle("dec", charset, want)
        for s, w, g in zip(strings, want, got):
            text = ebcdicjp.decode(bytes.fromhex(w), codepage)
            self.assertEqual(" ".join(f"{ord(c):04X}" for c in text), g, repr(s))

    def test_ibm930_matches_jdk(self):
        self._check("ibm930", "x-IBM930", 930)

    def test_ibm939_matches_jdk(self):
        self._check("ibm939", "x-IBM939", 939)

    def test_every_double_byte_code(self):
        for codepage, charset in (("ibm930", "x-IBM930"), ("ibm939", "x-IBM939")):
            t = load(codepage)
            codes = sorted(t.dbcs)
            got = oracle("dec", charset, [f"0E{c:04X}0F" for c in codes])
            for c, g in zip(codes, got):
                self.assertEqual(f"{t.dbcs[c]:04X}", g, f"{codepage} {c:04X}")


if __name__ == "__main__":
    unittest.main()
