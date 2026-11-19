import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from ebcdicjp.cli import main  # noqa: E402

CPY = os.path.join(HERE, "data", "custmast.cpy")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.jsonl = os.path.join(self.tmp, "r.jsonl")
        with open(self.jsonl, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"CUST-NO": 7, "CUST-KANJI": "佐藤", "BALANCE": "12.30", "STATUS-CD": "A"},
                                ensure_ascii=False) + "\n")
        self.dat = os.path.join(self.tmp, "c.dat")

    def test_encode_then_view(self):
        code, out, _ = run("encode", self.jsonl, "-c", CPY, "-o", self.dat, "--codepage", "ibm930")
        self.assertEqual(code, 0, out)
        code, out, err = run("view", self.dat, "-c", CPY)
        rec = json.loads(out.splitlines()[0])
        self.assertEqual((rec["CUST-NO"], rec["CUST-KANJI"], rec["BALANCE"]), (7, "佐藤", "12.30"))
        self.assertIn("0 problem", err)

    def test_broken_file_is_reported(self):
        run("encode", self.jsonl, "-c", CPY, "-o", self.dat, "--codepage", "ibm930")
        with open(self.dat, "ab") as fh:
            fh.write(b"\x40\x40\x40")  # trailing garbage: size is no longer a multiple of LRECL
        code, out, err = run("view", self.dat, "-c", CPY)
        self.assertIn("the last record is cut off", err)
        self.assertEqual(code, 1)  # the short last record is a problem

    def test_text(self):
        code, out, _ = run("text", "--encode", "山田")
        self.assertEqual(out.strip(), "0E 45 65 45 63 0F")
        code, out, _ = run("text", "0E4565", "45630F")
        self.assertEqual(out.strip(), "山田")

    def test_unknown_codepage(self):
        code, _, err = run("text", "C1", "--codepage", "cp932")
        self.assertEqual(code, 2)
        self.assertIn("ibm930", err)


class McpTests(unittest.TestCase):
    def test_tools_round_trip(self):
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "x.dat")
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "write_records", "arguments": {
                "records": [{"CUST-KANJI": "高橋", "BALANCE": "-1.00"}], "copybook": CPY, "output_path": out, "codepage": "ibm930"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_records", "arguments": {
                "path": out, "copybook": CPY}}},
        ]
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
        p = subprocess.run([sys.executable, "-m", "ebcdicjp.mcp_server"], input="\n".join(json.dumps(m) for m in msgs),
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        resp = [json.loads(ln) for ln in p.stdout.splitlines()]
        self.assertEqual(len(resp[1]["result"]["tools"]), 6)
        self.assertFalse(resp[2]["result"]["isError"], resp[2])
        rec = json.loads(resp[3]["result"]["content"][0]["text"])["records"][0]["value"]
        self.assertEqual((rec["CUST-KANJI"], rec["BALANCE"]), ("高橋", "-1.00"))


if __name__ == "__main__":
    unittest.main()
