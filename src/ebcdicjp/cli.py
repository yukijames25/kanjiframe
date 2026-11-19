"""ebcdicjp command line.

    ebcdicjp layout CUSTMAST.cpy                         # field offsets / lengths
    ebcdicjp view   CUST.dat -c CUSTMAST.cpy [--format jsonl|csv|md] [--codepage ibm930] [--rdw]
    ebcdicjp dump   CUST.dat -c CUSTMAST.cpy -n 1        # hex next to each value (for 文字化け hunting)
    ebcdicjp encode records.jsonl -c CUSTMAST.cpy -o CUST.dat   # test data: JSON -> fixed-length EBCDIC
    ebcdicjp text   0E45654563 0F --codepage ibm930       # decode hex bytes;  --encode "山田" for the reverse
    ebcdicjp detect CUST.dat [-c CUSTMAST.cpy]            # IBM930 or IBM939?
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

from . import __version__
from .api import detect_codepage, layout_rows, load_layout, read_records, text_preview, write_records
from .codec import encode_report
from .copybook import CopybookError, fields
from .record import RecordError
from .tables import canonical


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _layout(a):
    return load_layout(_read(a.copybook).decode(a.copybook_encoding), a.record)


def _flat(value, prefix=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _flat(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(value, list):
        for i, v in enumerate(value, 1):
            yield from _flat(v, f"{prefix}({i})")
    else:
        yield prefix, value


def _issue_line(i: dict) -> str:
    return f"  ! {i['path']} @{i['offset']} {i['kind']}: {i['detail']}"


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="ebcdicjp", description="日本語EBCDIC（IBM930/939）のメインフレームデータを読み書きする")
    ap.add_argument("--version", action="version", version=f"ebcdicjp {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, data=True):
        if data:
            p.add_argument("data", help="データファイル（固定長、または --rdw）")
        p.add_argument("-c", "--copybook", required=True, help="COBOL コピーブック")
        p.add_argument("--copybook-encoding", default="utf-8", help="コピーブックの文字コード（例: cp932）")
        p.add_argument("--record", help="01 レベルが複数あるときの名前")
        p.add_argument("--codepage", default="ibm930", help="ibm930（カナ）/ ibm939（英小文字）")
        p.add_argument("--rdw", action="store_true", help="可変長: 各レコードの先頭に4バイトの RDW")
        p.add_argument("--lrecl", type=int, help="レコード長（既定: コピーブックの長さ）")

    p = sub.add_parser("layout", help="コピーブックの項目・位置・長さを表示")
    p.add_argument("copybook")
    p.add_argument("--copybook-encoding", default="utf-8")
    p.add_argument("--record")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("view", help="レコードを JSONL / CSV / Markdown で表示")
    common(p)
    p.add_argument("--format", choices=["jsonl", "csv", "md"], default="jsonl")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("-n", "--limit", type=int)
    p.add_argument("--keep-spaces", action="store_true", help="末尾の空白を残す")
    p.add_argument("--use", action="append", help="REDEFINES のうち、このレコードで使う読み方（例: --use ADDR-JP）。複数指定可")

    p = sub.add_parser("dump", help="項目ごとに 16進 と値を並べて表示（文字化けの調査用）")
    common(p)
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("-n", "--limit", type=int, default=1)

    p = sub.add_parser("encode", help="JSON / JSONL のレコードから固定長の EBCDIC ファイルを作る（テストデータ用）")
    p.add_argument("records", help="JSONL（1行1レコード）または JSON の配列")
    common(p, data=False)
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("text", help="16進のバイト列を文字にする（--encode で逆）")
    p.add_argument("hex", nargs="*")
    p.add_argument("--codepage", default="ibm930")
    p.add_argument("--encode", help="この文字列を EBCDIC にする")
    p.add_argument("--dbcs", action="store_true", help="PIC N（SO/SI なしの2バイト）として扱う")

    p = sub.add_parser("detect", help="IBM930 と IBM939 のどちらかを推定")
    p.add_argument("data")
    p.add_argument("-c", "--copybook")
    p.add_argument("--copybook-encoding", default="utf-8")
    p.add_argument("--record")

    a = ap.parse_args(argv)
    try:
        if getattr(a, "codepage", None) and canonical(a.codepage) is None:
            raise ValueError(f"unknown code page {a.codepage!r}: use ibm930 or ibm939")
        if a.cmd == "layout":
            root = load_layout(_read(a.copybook).decode(a.copybook_encoding), a.record)
            rows = layout_rows(root)
            if a.json:
                print(json.dumps({"record": root.name, "length": root.size, "fields": rows}, ensure_ascii=False, indent=2))
            else:
                print(f"{root.name}  length={root.size}")
                for r in rows:
                    extra = f" V{r['scale']}" if r.get("scale") else ""
                    print(f"{r['pos']:>6} {r['length']:>5}  {r['kind']:<7}{extra:<4} {r['path']}  {r['pic'] or ''}")
            return 0

        if a.cmd in ("view", "dump"):
            root = _layout(a)
            res = read_records(_read(a.data), root, a.codepage, a.rdw, a.lrecl, a.skip, a.limit,
                               getattr(a, "keep_spaces", False), getattr(a, "use", None))
            for n in res["notes"]:
                print(f"note: {n}", file=sys.stderr)
            if a.cmd == "dump":
                data = _read(a.data)
                for rec in res["records"]:
                    print(f"# record {rec['index']} (byte {rec['offset']})")
                    raw = data[rec["offset"]:rec["offset"] + root.size]
                    flat = dict(_flat(rec["value"]))
                    by_path = {i["path"]: i for i in rec["issues"]}
                    for path, off, it in fields(root):
                        key = path.split(".", 1)[1] if "." in path else path
                        b = raw[off:off + it.size].hex(" ").upper()
                        mark = f"   ! {by_path[path]['kind']}: {by_path[path]['detail']}" if path in by_path else ""
                        print(f"{off + 1:>6} {path:<40} {flat.get(key, '')!s:<24} {b}{mark}")
                return 0
            if a.format == "jsonl":
                for rec in res["records"]:
                    print(json.dumps({"index": rec["index"], **rec["value"],
                                      **({"_issues": rec["issues"]} if rec["issues"] else {})}, ensure_ascii=False))
            elif a.format == "csv":
                buf = io.StringIO()
                w = None
                for rec in res["records"]:
                    row = dict(_flat(rec["value"]))
                    if w is None:
                        w = csv.DictWriter(buf, fieldnames=["index", *row.keys(), "issues"])
                        w.writeheader()
                    w.writerow({"index": rec["index"], **row,
                                "issues": "; ".join(f"{i['path']} {i['kind']}" for i in rec["issues"])})
                sys.stdout.write(buf.getvalue())
            else:
                for rec in res["records"]:
                    print(f"## record {rec['index']}\n\n| field | value |\n|---|---|")
                    alt = [i["path"].split(".", 1)[1] for i in rec["issues"] if i["kind"] == "alternative" and "." in i["path"]]
                    for k, v in _flat(rec["value"]):
                        if any(k == p or k.startswith(p + ".") for p in alt):
                            v = "（REDEFINES の別の読み方。このレコードでは使われていない）"
                        print(f"| {k} | {'' if v is None else v} |")
                    for i in rec["issues"]:
                        if i["kind"] != "alternative":
                            print(_issue_line(i))
                    print()
            bad = sum(1 for r in res["records"] for i in r["issues"] if i["kind"] not in ("blank", "alternative"))
            print(f"{len(res['records'])} of {res['records_in_file']} records, {bad} problem(s)", file=sys.stderr)
            return 1 if bad else 0

        if a.cmd == "encode":
            root = _layout(a)
            text = _read(a.records).decode("utf-8-sig").strip()
            records = json.loads(text) if text.startswith("[") else [json.loads(ln) for ln in text.splitlines() if ln.strip()]
            records = [{k: v for k, v in r.items() if k not in ("index", "_issues")} for r in records]
            data, notes = write_records(records, root, a.codepage, a.rdw)
            if os.path.exists(a.output) and os.path.samefile(a.output, a.records):
                raise ValueError("output must differ from the input")
            with open(a.output, "wb") as fh:
                fh.write(data)
            for n in notes:
                print(f"note: record {n['record']} {n['path']}: {n['detail']}", file=sys.stderr)
            print(json.dumps({"written": a.output, "records": len(records), "bytes": len(data),
                              "record_length": root.size, "one_way_characters": len(notes)}, ensure_ascii=False))
            return 0

        if a.cmd == "text":
            if a.encode is not None:
                data, issues = encode_report(a.encode, a.codepage, dbcs_only=a.dbcs)
                print(data.hex(" ").upper())
                for i in issues:
                    print(f"! {i.kind} @{i.offset}: {i.detail}", file=sys.stderr)
                return 1 if any(i.kind == "unencodable" for i in issues) else 0
            data = bytes.fromhex("".join(a.hex))
            if a.dbcs:
                from .codec import decode_report
                text, issues = decode_report(data, a.codepage, dbcs_only=True)
                res = {"text": text, "issues": [i.to_dict() for i in issues]}
            else:
                res = text_preview(data, a.codepage)
            print(res["text"])
            for i in res["issues"]:
                print(f"! {i['kind']} @{i['offset']}: {i['detail']}", file=sys.stderr)
            return 1 if res["issues"] else 0

        if a.cmd == "detect":
            root = load_layout(_read(a.copybook).decode(a.copybook_encoding), a.record) if a.copybook else None
            print(json.dumps(detect_codepage(_read(a.data), root), ensure_ascii=False, indent=2))
            return 0
    except (OSError, ValueError, CopybookError, RecordError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
