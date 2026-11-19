# ebcdicjp

**メインフレームの日本語データ（EBCDIC のカナ・漢字、COBOL のレコード）を、開発PCや AI エージェントから読み書きするツール。**
Python 標準ライブラリだけで動きます（依存ゼロ）。

*ebcdicjp reads and writes Japanese mainframe data — EBCDIC IBM930/939 kana and kanji with SO/SI, COBOL copybook layouts, packed and zoned decimals — with zero dependencies. CLI, Python codecs and an MCP server for AI agents.*

## なぜ

メインフレームの移行・保守では、本番から抜いた固定長データ（コピーブック付き）を開発PCで確かめたい場面がよくあります。
でも、Python の標準ライブラリには日本語 EBCDIC（IBM930 / IBM939）のコーデックがありません（`cp930` は `LookupError`）。
欧米向けの手順（cp037）では、漢字の SO/SI やカナ／英小文字の違いを扱えず、変換は商用製品に頼ることになります。

## できること

```
$ ebcdicjp layout CUSTMAST.cpy
CUST-REC  length=224
     1    10  zoned       CUST-REC.CUST-NO  9(10)
    11    30  text        CUST-REC.CUST-KANA  X(30)
    41    40  dbcs        CUST-REC.CUST-KANJI  N(20)
    89     8  packed  V2  CUST-REC.BALANCE  S9(13)V99
    ...

$ ebcdicjp view CUST.dat -c CUSTMAST.cpy --format md --use ADDR-JP
## record 1
| CUST-KANJI | 山田太郎 |
| BALANCE | 1234567.89 |
| ADDR-JP.ADDR-REST | 千代田区丸の内１−１−１ |
...
## record 5
| BALANCE |  |
  ! CUST-REC.BALANCE @88 bad-number: byte 2 (4A): A is not a digit
```

- **コーデック**：IBM930（カナ）・IBM939（英小文字）。SO(0E)/SI(0F) で切り替わる漢字、PIC N（SO/SI なしの2バイト）。
  `b"...".decode("ibm930")` のように Python の `codecs` からも使えます。
- **数値**：パック10進（COMP-3）、ゾーン10進（符号付き・SIGN SEPARATE）、バイナリ（COMP）。金額は Decimal で桁を落としません。
- **コピーブック**：PIC X / N / G / 9 / S9 / V、COMP-3 / COMP / BINARY / DISPLAY-1、OCCURS（DEPENDING ON は最大で配置）、REDEFINES、FILLER、固定形式（1〜6桁目の連番・7桁目のコメント）。
- **問題の場所を示す**：読めないバイト、SO/SI の崩れ、数字でないパック10進などを「項目のパス・バイト位置・実際のバイト」で報告します。黙って置き換えません。
- **戻らない文字を知らせる**：「〜」(U+301C) は 43A1 に変換され、読み戻すと「～」(U+FF5E) になります。こうした文字（52種）を書き込み時に報告します。
- **テストデータを作る**：JSON から固定長の EBCDIC ファイルを作ります（`encode`）。
- **AI エージェントから使う**：MCP サーバー（`describe_layout` / `read_records` / `write_records` / `decode_bytes` / `encode_text` / `detect_codepage`）。

## 正しさの確かめ方

変換表は JDK（Java）の `x-IBM930` / `x-IBM939` から生成し（`tools/GenTables.java`）、テストで次を突き合わせています。

- 2バイトの全コード（各 11,635 個）が JDK と同じ文字になること
- 漢字・カナ・英数・半角カナを混ぜたランダムな 1,200 個の文字列が、JDK と**同じバイト列**（SO/SI の位置を含む）になること
- Java で独立に作ったデータファイル（`tools/MakeSample.java`）を正しく読めること

`java` が入っていればこの突き合わせも実行されます。

## インストールと使い方

```bash
pip install git+https://github.com/yukijames25/ebcdicjp
ebcdicjp layout CUSTMAST.cpy                          # 項目の位置と長さ
ebcdicjp view   CUST.dat -c CUSTMAST.cpy -n 5          # JSONL（--format csv / md も可）
ebcdicjp dump   CUST.dat -c CUSTMAST.cpy -n 1          # 項目ごとに16進と値（文字化けの調査）
ebcdicjp detect CUST.dat -c CUSTMAST.cpy               # IBM930 と IBM939 のどちらか
ebcdicjp encode records.jsonl -c CUSTMAST.cpy -o TEST.dat   # テストデータを作る
ebcdicjp text --encode "山田〜"                        # 文字列 → 16進（戻らない文字も表示）
ebcdicjp text 0E 45 65 45 63 0F                        # 16進 → 文字列
```

- `--codepage ibm939`：英小文字を含む場合（既定は ibm930）
- `--rdw`：可変長（各レコードの先頭に4バイトの RDW）
- `--use ADDR-JP`：REDEFINES のどちらの読み方を使うか（どちらで読んでも文字として成り立つことがあるため、レコード種別の規則を知っている人が指定します）
- `--copybook-encoding cp932`：コピーブックが Shift_JIS のとき

**Claude Code から使う**

```bash
claude mcp add ebcdicjp -- ebcdicjp-mcp
```

`.claude/skills/ebcdicjp/` に、エージェント向けの手順（スキル）があります。

## 制限

- 対応する文字コードは IBM930 / IBM939（日本語 EBCDIC の代表的な2つ）です。KEIS（日立）・JEF（富士通）は、仕様を確かめてから対応予定です。
- 外字（ユーザー定義文字）の領域は、JDK の変換表に無いため「unmapped」として報告します。
- COMP-1 / COMP-2（浮動小数点）、SIGN の符号位置が特殊なもの、RENAMES（66 レベル）は未対応です。
- REDEFINES は、どちらの読み方も表示し、片方だけが正しく読めるときはもう片方を「alternative」として目立たなくします。どちらも文字として読めてしまう場合は `--use` で指定してください。

## 開発

```bash
python -m unittest discover -s tests           # java があれば JDK との突き合わせも
java tools/GenTables.java local && python tools/build_tables.py local   # 変換表の再生成
java tools/MakeSample.java tests/data/custmast_930.dat                 # サンプルデータの再生成
```

選んだ理由と調査は [docs/RESEARCH.md](docs/RESEARCH.md)。

License: MIT
