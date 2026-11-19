---
name: ebcdicjp
description: Read, check or create Japanese mainframe data — EBCDIC (IBM930/IBM939) files with kanji/kana, COBOL copybook layouts (.cpy), packed decimal (COMP-3), zoned or binary numbers. Use when the user has a fixed-length / RDW mainframe file, a copybook, hex bytes that look like 文字化け, or needs EBCDIC test data.
---

# ebcdicjp — 日本語メインフレームデータの読み書き

依存ゼロの Python ツール。このリポジトリ直下なら `PYTHONPATH=src`（PowerShell: `$env:PYTHONPATH="src"`）を付けて `python -m ebcdicjp ...`。インストール済みなら `ebcdicjp ...`。

## 手順

1. **レイアウトを読む**
   ```
   python -m ebcdicjp layout <copybook.cpy> [--copybook-encoding cp932]
   ```
   各項目の位置（1始まり）・長さ・種類を確認する。合計の長さがレコード長。

2. **数件だけ読む**
   ```
   python -m ebcdicjp view <data> -c <copybook.cpy> -n 5 --format md
   ```
   - 最後に出る「N of M records, K problem(s)」と、`!` の行（問題）を必ず確認する。
   - `note: file size ... is not a multiple of the record length` が出たら、レイアウト違い・RDW・改行入りを疑う（`--rdw` を試す）。
   - カナや英小文字が変なら `python -m ebcdicjp detect <data> -c <copybook.cpy>`。`ambiguous` のときは推測で決めず、両方の preview をユーザーに見せて確認する。

3. **問題を調べる**
   ```
   python -m ebcdicjp dump <data> -c <copybook.cpy> --skip <番号-1> -n 1
   ```
   項目ごとの16進と値が並ぶ。問題の種類:
   | kind | 意味 |
   |---|---|
   | bad-number | パック10進・ゾーン10進の中に数字でないバイト（転送時の破損、レイアウトのずれ） |
   | blank | 数値項目が空白（40）や LOW-VALUE（00）。エラーではないことが多い |
   | unmapped | 文字が割り当てられていないコード（外字の可能性、またはコードページ違い） |
   | bad-shift / odd-dbcs | SO/SI の対応が崩れている（項目の途中で切れている、転送時に削られた） |
   | alternative | REDEFINES の使われていない側。別の読み方が正しく読めている |
   | short | レコードが短い |

4. **REDEFINES**：どちらの読み方も文字として成り立つことがある。レコード種別の規則が分かれば `--use 項目名` で指定する。分からなければユーザーに聞く。

5. **テストデータを作る**
   ```
   python -m ebcdicjp encode records.jsonl -c <copybook.cpy> -o TEST.dat [--codepage ibm939]
   ```
   JSON の形は `view` の出力と同じ（グループはオブジェクト、OCCURS は配列、金額は "123.45" の文字列）。
   `note: ... reads back as ...` は、読み戻すと別の文字になる文字（〜→～、－→− など）。照合テストで差分の原因になるので、ユーザーに伝える。

## 守ること

- 読めないバイトを推測で埋めない。`!` の行（パス・位置・バイト）をそのまま報告する。
- 元のデータファイルは上書きしない。`encode` の出力先は別のファイルにする。
- 本番データには個人情報が含まれることがある。必要な件数だけ読み、外部に送らない。
