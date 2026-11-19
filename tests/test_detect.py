"""Behaviour found missing in stand-in test 1: 外字, OCCURS paths, auto-detection, the check command."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from ebcdicjp import decode_report  # noqa: E402
from ebcdicjp.api import load_layout, read_copybook, read_records, rdw_records, write_records  # noqa: E402
from ebcdicjp.cli import main  # noqa: E402

# Shift_JIS, fixed format: sequence numbers in 1-6, identifiers from column 73
COPYBOOK = (
    "000100* 社員マスタ\n"
    "000200 01  EMP-REC.                                                     EMP00010\n"
    "000300     05  EMP-ID                PIC X(8).                          EMP00020\n"
    "000400     05  EMP-NAME              PIC N(4).                          EMP00030\n"
    "000500     05  NOTE-TEXT             PIC X(20).                         EMP00040\n"
    "000600     05  ITEMS OCCURS 2 TIMES.                                    EMP00050\n"
    "000700         10  ITEM-NAME         PIC X(8).                          EMP00060\n"
    "000800         10  ITEM-AMT          PIC S9(5) COMP-3.                  EMP00070\n"
)
RECORDS = [
    {"EMP-ID": "E0000001", "EMP-NAME": "山田", "NOTE-TEXT": "hello world", "ITEMS": [{"ITEM-NAME": "a", "ITEM-AMT": "1"}]},
    {"EMP-ID": "E0000002", "EMP-NAME": "佐藤", "NOTE-TEXT": "good morning", "ITEMS": [{"ITEM-NAME": "手当", "ITEM-AMT": "2"}]},
    {"EMP-ID": "E0000003", "EMP-NAME": "鈴木", "NOTE-TEXT": "see you later", "ITEMS": []},
]


def build():
    """RDW, IBM939 file; record 2 loses the SI in ITEMS(1).ITEM-NAME, record 3 has a 外字 in EMP-NAME."""
    root = load_layout(read_copybook(COPYBOOK.encode("cp932"))[0])
    data, _ = write_records(RECORDS, root, "ibm939", rdw=True)
    data = bytearray(data)
    rec = root.size + 4
    item = 4 + 8 + 8 + 20  # RDW + EMP-ID + EMP-NAME + NOTE-TEXT
    for i in range(rec + item, rec + item + 8):
        if data[i] == 0x0F:
            data[i] = 0x40
    data[2 * rec + 4 + 8:2 * rec + 4 + 10] = b"\x69\x41"
    return root, bytes(data)


class DetectTests(unittest.TestCase):
    def test_copybook_encoding_falls_back_to_shift_jis(self):
        text, enc, note = read_copybook(COPYBOOK.encode("cp932"))
        self.assertEqual(enc, "cp932")
        self.assertIn("社員マスタ", text)
        self.assertIn("Shift_JIS", note)
        self.assertEqual(read_copybook(COPYBOOK.encode("utf-8"))[1], "utf-8")

    def test_rdw_and_code_page_are_detected_and_said(self):
        root, data = build()
        self.assertEqual(rdw_records(data), 3)
        self.assertIsNone(rdw_records(data[4:]))
        res = read_records(data, root)
        self.assertTrue(res["rdw"])
        self.assertEqual(res["codepage"], "ibm939")
        self.assertEqual(res["records_in_file"], 3)
        self.assertEqual(res["records"][0]["value"]["NOTE-TEXT"], "hello world")
        self.assertTrue(any("RDW" in n for n in res["notes"]))
        self.assertTrue(any("IBM939" in n for n in res["notes"]))

    def test_gaiji_is_reported_and_shown_as_geta(self):
        root, data = build()
        rec = read_records(data, root)["records"][2]
        self.assertEqual(rec["value"]["EMP-NAME"], "〓木")
        gaiji = [i for i in rec["issues"] if i["kind"] == "gaiji"]
        self.assertEqual(len(gaiji), 1)
        self.assertEqual(gaiji[0]["pos"], 9)  # 1-based, like the layout
        _, issues = decode_report(b"\x0e\x69\x41\x0f", "ibm930")
        self.assertEqual([i.kind for i in issues], ["gaiji"])

    def test_missing_si_points_at_occurs_element_and_its_so(self):
        root, data = build()
        issues = read_records(data, root)["records"][1]["issues"]
        self.assertEqual([(i["path"], i["kind"]) for i in issues], [("EMP-REC.ITEMS(1).ITEM-NAME", "bad-shift")])
        self.assertEqual(issues[0]["pos"], 37)  # where the SO is, i.e. where the kanji run began

    def test_check_lists_every_problem_with_the_key(self):
        root, data = build()
        with tempfile.TemporaryDirectory() as tmp:
            dat, cpy = os.path.join(tmp, "E.dat"), os.path.join(tmp, "E.cpy")
            with open(dat, "wb") as fh:
                fh.write(data)
            with open(cpy, "wb") as fh:
                fh.write(COPYBOOK.encode("cp932"))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["check", dat, "-c", cpy, "--key", "EMP-ID"])
        self.assertEqual(code, 1)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("EMP-ID=E0000002", lines[0])
        self.assertIn("ITEMS(1).ITEM-NAME  pos 37", lines[0])
        self.assertIn("EMP-ID=E0000003", lines[1])
        self.assertIn("gaiji", lines[1])
        self.assertIn("2 problems in 2 records", err.getvalue())
        self.assertIn("Shift_JIS", err.getvalue())


KANA_CPY = """       01  R.
           05  ID        PIC X(8).
           05  KANJI     PIC N(5).
           05  KANA      PIC X(20).
           05  AMT       PIC S9(7) COMP-3.
"""
NAMES = [("山田太郎", "ﾔﾏﾀﾞ ﾀﾛｳ"), ("渡邊花子", "ﾜﾀﾅﾍﾞ ﾊﾅｺ"), ("佐藤美紀", "ｻﾄｳ ﾐｷ"), ("中村健", "ﾅｶﾑﾗ ｹﾝ")]


class NoLowercaseTests(unittest.TestCase):
    """Stand-in test 2: IBM939 data without lowercase letters was read as IBM930 with garbled kana and no warning."""

    def test_kana_only_data_is_detected_both_ways(self):
        root = load_layout(KANA_CPY)
        recs = [{"ID": f"E{k:07}", "KANJI": a, "KANA": b, "AMT": "1"} for k, (a, b) in enumerate(NAMES)]
        for cp in ("ibm930", "ibm939"):
            res = read_records(write_records(recs, root, cp)[0], root)
            self.assertEqual(res["codepage"], cp)
            self.assertFalse(res["codepage_uncertain"])
            self.assertEqual(res["records"][0]["value"]["KANA"], "ﾔﾏﾀﾞ ﾀﾛｳ")

    def test_too_little_to_tell_is_flagged_not_silent(self):
        root = load_layout(KANA_CPY)
        data = write_records([{"ID": "E0000001", "KANJI": "佐藤", "KANA": "ｻﾄｳ ﾐｷ"}], root, "ibm939")[0]
        res = read_records(data, root)
        self.assertTrue(res["codepage_uncertain"])
        self.assertTrue(any("UNCERTAIN" in n for n in res["notes"]))

    def test_same_reading_is_not_a_worry(self):
        root = load_layout(KANA_CPY)
        data = write_records([{"ID": "E0000001", "KANJI": "佐藤", "KANA": "ABC 123"}], root, "ibm939")[0]
        res = read_records(data, root)
        self.assertFalse(res["codepage_uncertain"])


if __name__ == "__main__":
    unittest.main()
