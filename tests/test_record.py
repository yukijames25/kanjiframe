import os
import shutil
import sys
import unittest
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from kanjiframe import copybook, numbers  # noqa: E402
from kanjiframe.record import RecordError, decode_record, encode_record, split_records  # noqa: E402

CPY = open(os.path.join(HERE, "data", "custmast.cpy"), encoding="utf-8").read()
JAVA = shutil.which("java")


class NumberTests(unittest.TestCase):
    def test_packed_known_vectors(self):
        self.assertEqual(numbers.pack("-123.45", 4, 2), bytes.fromhex("0012345D"))
        self.assertEqual(numbers.unpack(bytes.fromhex("0012345D"), 2), Decimal("-123.45"))
        self.assertEqual(numbers.pack(7, 2, 0, signed=False), bytes.fromhex("007F"))
        with self.assertRaises(numbers.NumberError):
            numbers.unpack(bytes.fromhex("1A2C"))  # A is not a digit
        with self.assertRaises(numbers.NumberError):
            numbers.pack(123456, 3)  # 5 digits max

    def test_zoned_known_vectors(self):
        self.assertEqual(numbers.zone(-123, 3), bytes.fromhex("F1F2D3"))
        self.assertEqual(numbers.unzone(bytes.fromhex("F1F2C3")), 123)
        with self.assertRaises(numbers.NumberError) as e:
            numbers.unzone(bytes.fromhex("40F1"))
        self.assertIn("space", str(e.exception))

    def test_binary(self):
        self.assertEqual(numbers.binary(-2, 4), b"\xff\xff\xff\xfe")
        self.assertEqual(numbers.unbin(b"\x00\x00\x30\x39", 2), Decimal("123.45"))


class CopybookTests(unittest.TestCase):
    def test_layout(self):
        root = copybook.parse(CPY)[0]
        offs = {p: (o, it.size) for p, o, it in copybook.fields(root)}
        self.assertEqual(offs["CUST-REC.CUST-NO"], (0, 10))
        self.assertEqual(offs["CUST-REC.CUST-KANJI"], (40, 40))
        self.assertEqual(offs["CUST-REC.BALANCE"], (88, 8))
        self.assertEqual(offs["CUST-REC.CREDIT-LIMIT"], (96, 4))
        self.assertEqual(offs["CUST-REC.ACCTS(2).ACCT-NO"], (105 + 16 + 2, 7))
        self.assertEqual(offs["CUST-REC.ADDR-JP.ADDR-PREF"], offs["CUST-REC.ADDR-AREA"][:1] + (8,))
        self.assertEqual(root.size, 105 + 48 + 60 + 1 + 10)

    def test_redefines_larger_than_base(self):
        root = copybook.parse("""
       01 R.
          05 A PIC X(2).
          05 B REDEFINES A PIC X(5).
          05 C PIC X(1).
""")[0]
        offs = {p: o for p, o, _ in copybook.fields(root)}
        self.assertEqual(offs["R.C"], 5)
        self.assertEqual(root.size, 6)

    def test_nested_occurs(self):
        root = copybook.parse("""
       01 R.
          05 G OCCURS 2.
             10 H OCCURS 3 PIC X(2).
             10 K PIC 9.
""")[0]
        offs = [o for _, o, _ in copybook.fields(root)]
        self.assertEqual(offs, [0, 2, 4, 6, 7, 9, 11, 13])

    def test_free_format_and_edited(self):
        root = copybook.parse("01 R. *> free format\n 05 AMT PIC ZZZ,ZZ9.99. 05 D PIC S9(5) SIGN LEADING SEPARATE.")[0]
        kinds = [(it.kind, it.size) for _, _, it in copybook.fields(root)]
        self.assertEqual(kinds, [("text", 10), ("zoned", 6)])


class RecordTests(unittest.TestCase):
    rec = {
        "CUST-NO": 1234567890,
        "CUST-KANA": "ﾔﾏﾀﾞ ﾀﾛｳ",
        "CUST-KANJI": "山田太郎",
        "BIRTH-DATE": {"BIRTH-YYYY": 1985, "BIRTH-MM": 6, "BIRTH-DD": 15},
        "BALANCE": "-1234567.89",
        "CREDIT-LIMIT": 500000,
        "BRANCH-CD": "123",
        "ACCT-COUNT": 2,
        "ACCTS": [{"ACCT-TYPE": "01", "ACCT-NO": 1111111, "ACCT-BAL": "100.00"},
                  {"ACCT-TYPE": "02", "ACCT-NO": 2222222, "ACCT-BAL": "-5.50"}],
        "ADDR-JP": {"ADDR-PREF": "東京都", "ADDR-REST": "千代田区丸の内１－１"},
        "STATUS-CD": "A",
    }

    def setUp(self):
        self.root = copybook.parse(CPY)[0]

    def test_round_trip(self):
        data, notes = encode_record(self.rec, self.root, "ibm930")
        self.assertEqual(len(data), self.root.size)
        back, issues = decode_record(data, self.root, "ibm930")
        self.assertEqual(back["CUST-KANJI"], "山田太郎")
        self.assertEqual(back["BALANCE"], "-1234567.89")
        self.assertEqual(back["ACCTS"][1]["ACCT-BAL"], "-5.50")
        self.assertEqual(back["ACCTS"][2]["ACCT-NO"], 0)
        self.assertEqual(back["ADDR-JP"]["ADDR-REST"], "千代田区丸の内１−１")  # IBM930 reads 4260 as U+2212
        self.assertEqual([n["kind"] for n in notes], ["one-way"])  # and says so when writing
        self.assertEqual({i["kind"] for i in issues if i["kind"] != "blank"}, {"alternative"})  # ADDR-AREA (PIC X) vs ADDR-JP (PIC N)

    def test_errors_are_specific(self):
        bad = dict(self.rec, **{"CUST-KANJI": "山田太郎" * 6})
        with self.assertRaises(RecordError) as e:
            encode_record(bad, self.root)
        self.assertIn("double-byte characters", str(e.exception))
        with self.assertRaises(RecordError):
            encode_record({"NO-SUCH": 1}, self.root)
        with self.assertRaises(RecordError):
            encode_record({"ADDR-AREA": "x", "ADDR-JP": {"ADDR-PREF": "東京"}}, self.root)

    def test_bad_bytes_are_located(self):
        data = bytearray(encode_record(self.rec, self.root)[0])
        data[88] = 0xAB  # break the packed BALANCE
        _, issues = decode_record(bytes(data), self.root)
        hit = [i for i in issues if i["kind"] == "bad-number"]
        self.assertEqual(hit[0]["path"], "CUST-REC.BALANCE")
        self.assertEqual(hit[0]["offset"], 88)

    def test_split_rdw(self):
        recs = b"\x00\x07\x00\x00abc" + b"\x00\x05\x00\x00d"
        self.assertEqual([r for _, _, r in split_records(recs, 0, rdw=True)], [b"abc", b"d"])

    @unittest.skipUnless(JAVA, "java not installed")
    def test_text_fields_match_jdk(self):
        from test_codec import oracle
        data, _ = encode_record(self.rec, self.root, "ibm930")
        kana = oracle("enc", "x-IBM930", [" ".join(f"{ord(c):04X}" for c in "ﾔﾏﾀﾞ ﾀﾛｳ")])[0]
        self.assertTrue(data[10:40].hex().upper().startswith(kana))


if __name__ == "__main__":
    unittest.main()
