"""ebcdicjp command line.

    ebcdicjp layout CUSTMAST.cpy                         # field positions / lengths
    ebcdicjp view   CUST.dat -c CUSTMAST.cpy [--format jsonl|csv|md]
    ebcdicjp check  CUST.dat -c CUSTMAST.cpy --key CUST-NO   # every problem in the file, one line each
    ebcdicjp dump   CUST.dat -c CUSTMAST.cpy --skip 4 -n 1   # hex next to each value (for 文字化け hunting)
    ebcdicjp encode records.jsonl -c CUSTMAST.cpy -o CUST.dat --codepage ibm930   # test data
    ebcdicjp text   0E 45 65 45 63 0F                     # decode hex bytes;  --encode "山田" for the reverse
    ebcdicjp detect CUST.dat [-c CUSTMAST.cpy]            # IBM930 or IBM939?

Code page, RDW and the copybook's encoding are detected unless given; what was assumed is
printed as "note:" lines. Byte positions are 1-based everywhere, like the layout.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

from . import __version__
from .api import (detect_codepage, layout_rows, load_layout, read_copybook, read_records, text_preview,
                  write_records)
from .codec import decode_report, encode_report
from .copybook import CopybookError, fields
from .record import RecordError
from .tables import canonical

NOT_PROBLEMS = ("blank", "alternative")


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _note(text: str) -> None:
    print(f"note: {text}", file=sys.stderr)


def _layout(a):
    text, _enc, note = read_copybook(_read(a.copybook), a.copybook_encoding)
    if note:
        _note(note)
    return load_layout(text, a.record)


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
    return f"  ! {i['path']}  pos {i['pos']}  {i['kind']}: {i['detail']}"


def _key_value(flat: dict, key: str):
    """Value of the field named *key* (its name, or the end of its path) in a flattened record."""
    k = key.upper()
    for path, v in flat.items():
        p = path.upper()
        if p == k or p.endswith("." + k):
            return v
    return None


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="ebcdicjp", description="日本語EBCDIC（IBM930/939）のメインフレームデータを読み書きする")
    ap.add_argument("--version", action="version", version=f"ebcdicjp {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def copybook_opts(p, required=True):
        p.add_argument("-c", "--copybook", required=required, help="COBOL コピーブック")
        p.add_argument("--copybook-encoding", default="auto",
                       help="コピーブックの文字コード（既定 auto: UTF-8、だめなら Shift_JIS）")
        p.add_argument("--record", help="01 レベルが複数あるときの名前")

    def framing(p):
        p.add_argument("--rdw", action=argparse.BooleanOptionalAction, default=None,
                       help="可変長（各レコードの先頭に4バイトの RDW）。既定はファイルから判定")
        p.add_argument("--lrecl", type=int, help="レコード長（既定: コピーブックの長さ）")

    def common(p, data=True):
        if data:
            p.add_argument("data", help="データファイル（固定長、または RDW 付き可変長）")
        copybook_opts(p)
        p.add_argument("--codepage", default="auto", help="auto（既定）/ ibm930（カナ）/ ibm939（英小文字）")
        framing(p)

    def paging(p, n=None):
        p.add_argument("--skip", type=int, default=0, help="先頭から飛ばすレコード数（5件目を見るなら --skip 4）")
        p.add_argument("-n", "--limit", type=int, default=n, help="表示するレコード数" + (f"（既定 {n}）" if n else ""))

    p = sub.add_parser("layout", help="コピーブックの項目・位置・長さを表示")
    p.add_argument("copybook")
    p.add_argument("--copybook-encoding", default="auto")
    p.add_argument("--record")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("view", help="レコードを JSONL / CSV / Markdown で表示")
    common(p)
    p.add_argument("--format", choices=["jsonl", "csv", "md"], default="jsonl")
    paging(p)
    p.add_argument("--keep-spaces", action="store_true", help="末尾の空白を残す")
    p.add_argument("--use", action="append", help="REDEFINES のうち、このレコードで使う読み方（例: --use ADDR-JP）。複数指定可")

    p = sub.add_parser("check", help="ファイル全体の問題を1行ずつ一覧（--key で社員番号などを添える）")
    common(p)
    p.add_argument("--key", action="append", help="各行に添える項目（例: --key EMP-ID）。複数指定可")
    p.add_argument("--format", choices=["text", "csv", "jsonl"], default="text")
    p.add_argument("--use", action="append", help="REDEFINES の読み方（view と同じ）")

    p = sub.add_parser("dump", help="項目ごとに 16進 と値を並べて表示（文字化けの調査用）")
    common(p)
    paging(p, 1)

    p = sub.add_parser("encode", help="JSON / JSONL のレコードから EBCDIC ファイルを作る（テストデータ用）")
    p.add_argument("records", help="JSONL（1行1レコード）または JSON の配列。形は view の出力と同じ")
    copybook_opts(p)
    p.add_argument("--codepage", required=True, help="ibm930（カナ）/ ibm939（英小文字）。相手のシステムに合わせる")
    p.add_argument("--rdw", action="store_true", help="可変長（各レコードの先頭に4バイトの RDW）で書く")
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("text", help="16進のバイト列を文字にする（--encode で逆）")
    p.add_argument("hex", nargs="*")
    p.add_argument("--codepage", default="auto", help="auto（既定: 930 と 939 で読みが違えば両方表示）/ ibm930 / ibm939")
    p.add_argument("--encode", help="この文字列を EBCDIC にする")
    p.add_argument("--dbcs", action="store_true", help="PIC N（SO/SI なしの2バイト）として扱う")

    p = sub.add_parser("detect", help="IBM930 と IBM939 のどちらかを推定")
    p.add_argument("data")
    copybook_opts(p, required=False)
    framing(p)

    a = ap.parse_args(argv)
    try:
        cp = getattr(a, "codepage", None)
        if cp and cp != "auto" and canonical(cp) is None:
            raise ValueError(f"unknown code page {cp!r}: use ibm930 or ibm939")
        if a.cmd == "layout":
            root = _layout(a)
            rows = layout_rows(root)
            if a.json:
                print(json.dumps({"record": root.name, "length": root.size, "fields": rows}, ensure_ascii=False, indent=2))
            else:
                print(f"{root.name}  length={root.size}")
                for r in rows:
                    extra = f" V{r['scale']}" if r.get("scale") else ""
                    print(f"{r['pos']:>6} {r['length']:>5}  {r['kind']:<7}{extra:<4} {r['path']}  {r['pic'] or ''}")
            return 0

        if a.cmd in ("view", "dump", "check"):
            root = _layout(a)
            data = _read(a.data)
            skip, limit = (0, None) if a.cmd == "check" else (a.skip, a.limit)
            res = read_records(data, root, a.codepage, a.rdw, a.lrecl, skip, limit,
                               getattr(a, "keep_spaces", False), getattr(a, "use", None))
            for n in res["notes"]:
                _note(n)
            if a.cmd == "dump":
                for rec in res["records"]:
                    print(f"# record {rec['index']} (starts at byte {rec['offset'] + 1} of the file)")
                    raw = data[rec["offset"]:rec["offset"] + root.size]
                    flat = dict(_flat(rec["value"]))
                    by_path: dict[str, list] = {}
                    for i in rec["issues"]:
                        by_path.setdefault(i["path"], []).append(i)
                    print(f"{'pos':>6} {'field':<40} {'value':<24} hex")
                    for path, off, it in fields(root):
                        key = path.split(".", 1)[1] if "." in path else path
                        b = raw[off:off + it.size].hex(" ").upper()
                        mark = "".join(f"   ! pos {i['pos']} {i['kind']}: {i['detail']}" for i in by_path.get(path, []))
                        print(f"{off + 1:>6} {path:<40} {'' if flat.get(key) is None else flat.get(key)!s:<24} {b}{mark}")
                return 0
            if a.cmd == "check":
                return _check(a, res)
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
                                "issues": "; ".join(f"{i['path']} pos {i['pos']} {i['kind']}" for i in rec["issues"])})
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
            sys.stdout.flush()
            bad = sum(1 for r in res["records"] for i in r["issues"] if i["kind"] not in NOT_PROBLEMS)
            print(f"{len(res['records'])} of {res['records_in_file']} records ({res['codepage'].upper()}"
                  f"{', RDW' if res['rdw'] else ''}), {bad} problem(s)", file=sys.stderr)
            return 1 if bad else 0

        if a.cmd == "encode":
            if canonical(a.codepage) is None:
                raise ValueError(f"unknown code page {a.codepage!r}: use ibm930 or ibm939")
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
                _note(f"record {n['record']} {n['path']}: {n['detail']}")
            print(json.dumps({"written": a.output, "codepage": canonical(a.codepage), "rdw": a.rdw,
                              "records": len(records), "bytes": len(data),
                              "record_length": root.size, "one_way_characters": len(notes)}, ensure_ascii=False))
            return 0

        if a.cmd == "text":
            cps = ["ibm930", "ibm939"] if a.codepage == "auto" else [a.codepage]
            if a.encode is not None:
                outs = {c: encode_report(a.encode, c, dbcs_only=a.dbcs) for c in cps}
                same = len({o[0] for o in outs.values()}) == 1
                worst = 0
                for c, (data, issues) in outs.items():
                    print(data.hex(" ").upper() if same else f"{c}: {data.hex(' ').upper()}")
                    for i in issues:
                        print(f"! {i.kind} (character {i.offset + 1}): {i.detail}", file=sys.stderr)
                    worst = max(worst, 1 if any(i.kind == "unencodable" for i in issues) else 0)
                    if same:
                        break
                return worst
            data = bytes.fromhex("".join(a.hex))
            outs = {c: decode_report(data, c, dbcs_only=a.dbcs, gaiji_mark="〓") for c in cps}
            same = len({o[0] for o in outs.values()}) == 1
            if not same:
                _note("IBM930 and IBM939 read these bytes differently; both are shown (use --codepage to pick one)")
            worst = 0
            for c, (text, issues) in outs.items():
                print(text if same else f"{c}: {text}")
                for i in issues:
                    print(f"! {i.kind} (byte {i.offset + 1}): {i.detail}", file=sys.stderr)
                worst = max(worst, 1 if issues else 0)
                if same:
                    break
            return worst

        if a.cmd == "detect":
            root = _layout(a) if a.copybook else None
            print(json.dumps(detect_codepage(_read(a.data), root, rdw=a.rdw, lrecl=a.lrecl), ensure_ascii=False, indent=2))
            return 0
    except (OSError, ValueError, CopybookError, RecordError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def _check(a, res) -> int:
    keys = a.key or []
    rows = []
    for rec in res["records"]:
        flat = dict(_flat(rec["value"]))
        kv = {k: _key_value(flat, k) for k in keys}
        for i in rec["issues"]:
            if i["kind"] == "alternative":
                continue
            rows.append({"record": rec["index"], **kv, "field": i["path"], "pos": i["pos"],
                         "bytes": i.get("bytes", ""), "kind": i["kind"], "detail": i["detail"]})
    missing = [k for k in keys if rows and all(r[k] is None for r in rows)]
    if missing:
        _note(f"key field(s) not found in the layout: {', '.join(missing)}")
    if a.format == "jsonl":
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    elif a.format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["record", *keys, "field", "pos", "bytes", "kind", "detail"])
        w.writeheader()
        w.writerows(rows)
        sys.stdout.write(buf.getvalue())
    else:
        for r in rows:
            key = "  ".join(f"{k}={r[k]}" for k in keys)
            print(f"record {r['record']}{'  ' + key if key else ''}  {r['field']}  pos {r['pos']}"
                  f"{'  [' + r['bytes'] + ']' if r['bytes'] else ''}  {r['kind']}: {r['detail']}")
    sys.stdout.flush()
    problems = [r for r in rows if r["kind"] not in NOT_PROBLEMS]
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    recs = len({r["record"] for r in problems})
    kinds = ", ".join(f"{k} {n}" for k, n in sorted(by_kind.items()))
    print(f"{res['records_in_file']} records ({res['codepage'].upper()}{', RDW' if res['rdw'] else ''}): "
          f"{len(problems)} problem(s) in {recs} record(s)"
          f"{' — ' + kinds if kinds else ''}"
          f"{'  (blank = empty numeric field: often intended, but check)' if 'blank' in by_kind else ''}",
          file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
