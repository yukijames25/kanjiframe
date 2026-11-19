"""Zero-dependency MCP (Model Context Protocol) stdio server for ebcdicjp.

Register with Claude Code:
    claude mcp add ebcdicjp -- ebcdicjp-mcp
"""
from __future__ import annotations

import json
import os
import sys
import traceback

from . import __version__
from .api import detect_codepage, layout_rows, load_layout, read_records, text_preview, write_records
from .codec import encode_report

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

_CP = {"type": "string", "enum": ["ibm930", "ibm939"], "default": "ibm930",
       "description": "ibm930 = katakana in single-byte (no lowercase); ibm939 = Latin with lowercase. Use detect_codepage if unsure."}
_CB = {"type": "string", "description": "Absolute path to the COBOL copybook"}

TOOLS = [
    {
        "name": "describe_layout",
        "description": "Parse a COBOL copybook and list every field with its byte position, length and type "
                       "(text = PIC X with SO/SI kanji, dbcs = PIC N, zoned, packed = COMP-3, binary = COMP).",
        "inputSchema": {"type": "object", "properties": {"copybook": _CB, "record": {"type": "string"},
                                                          "copybook_encoding": {"type": "string", "default": "utf-8"}},
                        "required": ["copybook"]},
    },
    {
        "name": "read_records",
        "description": "Decode records of a Japanese mainframe data file (fixed-length, or variable with RDW) using a "
                       "copybook. Returns nested JSON per record plus issues located by field path and byte offset "
                       "(unmapped bytes, broken SO/SI, invalid packed/zoned numbers). Read a few records first (limit).",
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Absolute path to the data file"}, "copybook": _CB, "codepage": _CP,
            "record": {"type": "string"}, "rdw": {"type": "boolean", "default": False},
            "lrecl": {"type": "integer"}, "skip": {"type": "integer", "default": 0},
            "limit": {"type": "integer", "default": 20}, "copybook_encoding": {"type": "string", "default": "utf-8"},
            "use": {"type": "array", "items": {"type": "string"},
                    "description": "REDEFINES readings that apply to this file, e.g. [\"ADDR-JP\"]; the others are omitted"}},
            "required": ["path", "copybook"]},
    },
    {
        "name": "write_records",
        "description": "Build a fixed-length EBCDIC file (test data) from JSON records shaped like read_records output. "
                       "Missing fields are spaces / zero. Reports characters that will not read back the same (〜 → ～).",
        "inputSchema": {"type": "object", "properties": {
            "records": {"type": "array", "items": {"type": "object"}}, "copybook": _CB, "codepage": _CP,
            "output_path": {"type": "string"}, "record": {"type": "string"}, "rdw": {"type": "boolean", "default": False},
            "copybook_encoding": {"type": "string", "default": "utf-8"}},
            "required": ["records", "copybook", "output_path"]},
    },
    {
        "name": "decode_bytes",
        "description": "Decode hex bytes (e.g. from a hex dump or an error message) as Japanese EBCDIC, with problems listed.",
        "inputSchema": {"type": "object", "properties": {"hex": {"type": "string"}, "codepage": _CP,
                                                          "dbcs_only": {"type": "boolean", "default": False}},
                        "required": ["hex"]},
    },
    {
        "name": "encode_text",
        "description": "Encode text to Japanese EBCDIC hex (SO/SI added around kanji). Lists unencodable and one-way characters.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "codepage": _CP,
                                                          "dbcs_only": {"type": "boolean", "default": False}},
                        "required": ["text"]},
    },
    {
        "name": "detect_codepage",
        "description": "Guess whether a data file is IBM930 or IBM939 (says 'ambiguous' with both previews when it can't tell).",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "copybook": _CB,
                                                          "copybook_encoding": {"type": "string", "default": "utf-8"}},
                        "required": ["path"]},
    },
]


def _text(obj, error: bool = False) -> dict:
    if not isinstance(obj, str):
        obj = json.dumps(obj, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": obj}], "isError": error}


def _file(path) -> bytes:
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")
    with open(path, "rb") as fh:
        return fh.read()


def _layout(args):
    return load_layout(_file(args["copybook"]).decode(args.get("copybook_encoding") or "utf-8"), args.get("record"))


def call_tool(name: str, a: dict) -> dict:
    cp = a.get("codepage") or "ibm930"
    if name == "describe_layout":
        root = _layout(a)
        return _text({"record": root.name, "length": root.size, "fields": layout_rows(root)})
    if name == "read_records":
        root = _layout(a)
        res = read_records(_file(a["path"]), root, cp, bool(a.get("rdw")), a.get("lrecl"),
                           int(a.get("skip") or 0), int(a.get("limit") or 20), use=a.get("use"))
        return _text(res)
    if name == "write_records":
        out = a["output_path"]
        if os.path.exists(out):
            return _text(f"refusing to overwrite an existing file: {out}", True)
        data, notes = write_records(a["records"], _layout(a), cp, bool(a.get("rdw")))
        with open(out, "wb") as fh:
            fh.write(data)
        return _text({"written": out, "bytes": len(data), "records": len(a["records"]), "notes": notes})
    if name == "decode_bytes":
        data = bytes.fromhex(a["hex"].replace(" ", ""))
        if a.get("dbcs_only"):
            from .codec import decode_report
            text, issues = decode_report(data, cp, dbcs_only=True)
            return _text({"text": text, "issues": [i.to_dict() for i in issues]})
        return _text(text_preview(data, cp))
    if name == "encode_text":
        data, issues = encode_report(a["text"], cp, dbcs_only=bool(a.get("dbcs_only")))
        return _text({"hex": data.hex(" ").upper(), "length": len(data), "issues": [i.to_dict() for i in issues]})
    if name == "detect_codepage":
        root = _layout(a) if a.get("copybook") else None
        return _text(detect_codepage(_file(a["path"]), root))
    return _text(f"unknown tool: {name}", True)


def handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:
        return None
    try:
        if method == "initialize":
            req = (msg.get("params") or {}).get("protocolVersion")
            result = {
                "protocolVersion": req if req in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ebcdicjp", "version": __version__},
                "instructions": ("Japanese mainframe data: start with describe_layout on the copybook, then read_records "
                                 "with a small limit. If kana or lowercase look wrong, try detect_codepage. Report the "
                                 "issues read_records returns instead of guessing what the bytes meant."),
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            try:
                result = call_tool(params.get("name", ""), params.get("arguments") or {})
            except Exception as e:
                result = _text(f"{type(e).__name__}: {e}", True)
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}


def main() -> None:
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(msg, list):
                resp = [r for r in (handle(m) for m in msg) if r is not None] or None
            else:
                resp = handle(msg)
        if resp is not None:
            sys.stdout.buffer.write(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
