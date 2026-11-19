---
name: ebcdicjp
description: Read, check or create Japanese mainframe data — EBCDIC (IBM930/IBM939) files with kanji/kana, COBOL copybook layouts (.cpy), packed decimal (COMP-3), zoned or binary numbers. Use when the user has a fixed-length / RDW mainframe file, a copybook, hex bytes that look like 文字化け, or needs EBCDIC test data.
---

# ebcdicjp — 日本語メインフレームデータの読み書き

依存ゼロの Python ツール。このリポジトリ直下なら `PYTHONPATH=src`（PowerShell: `$env:PYTHONPATH="src"`）を付けて `python -m ebcdicjp ...`。インストール済みなら `ebcdicjp ...`。

## 手順

1. **レイアウトを読む**
   ```
   python -m ebcdicjp layout <copybook.cpy>
   ```
   各項目の位置（1始まり）・長さ・種類を確認する。合計の長さがレコード長。

2. **数件だけ読む**
   ```
   python -m ebcdicjp view <data> -c <copybook.cpy> -n 5 --format md
   ```
   - コードページ・RDW・コピーブックの文字コードは自動で判定され、`note:` に何を仮定したかが出る。**note は必ず読んでユーザーにも伝える**。違っていれば `--codepage ibm939` / `--no-rdw` / `--copybook-encoding` で上書きする。
   - `could not tell IBM930 from IBM939` のときは推測で決めず、`detect` の両方の preview をユーザーに見せて確認する。
   - `not a multiple of the record length ... not an RDW chain either` は、レイアウト違い・`--lrecl`・転送時の改行混入を疑う。

3. **全件の問題を一覧する**
   ```
   python -m ebcdicjp check <data> -c <copybook.cpy> --key <社員番号などの項目名>
   ```
   1行に1問題（レコード番号・キー・項目のパス・位置（1始まり）・バイト・種類）。最後の行が件数のまとめ。`--format csv` で表にもできる。

4. **1件を詳しく調べる**
   ```
   python -m ebcdicjp dump <data> -c <copybook.cpy> --skip <レコード番号-1> -n 1
   ```
   項目ごとの位置・値・16進が並ぶ。問題の種類:
   | kind | 意味 |
   |---|---|
   | bad-number | パック10進・ゾーン10進の中に数字でないバイト（転送時の破損、レイアウトのずれ） |
   | blank | 数値項目が空白（40）や LOW-VALUE（00）。意図した空のこともあるが、ユーザーに確認する |
   | gaiji | 外字（ユーザー定義領域 6941〜7FFE）。値は「〓」。何の字かはその会社の外字表が無いと分からないので、推測せずコードを伝える |
   | unmapped | 文字が割り当てられていないコード（コードページ違いの可能性） |
   | bad-shift / odd-dbcs | SO/SI の対応が崩れている。SI が無いときは漢字が始まった SO の位置を指す（項目の途中で切れた、転送時に削られた） |
   | alternative | REDEFINES の使われていない側。別の読み方が正しく読めている |
   | short | レコードが短い |

5. **REDEFINES**：どちらの読み方も文字として成り立つことがある。レコード種別の規則が分かれば `--use 項目名` で指定する。分からなければユーザーに聞く。

6. **テストデータを作る**
   ```
   python -m ebcdicjp encode records.jsonl -c <copybook.cpy> -o TEST.dat --codepage <ibm930|ibm939> [--rdw]
   ```
   コードページと RDW は、読み込む側のシステム（元データの note）に合わせる。
   JSON の形は `view` の出力と同じ（グループはオブジェクト、OCCURS は配列、金額は "123.45" の文字列）。省いた項目は空白／ゼロ、FILLER は書かなくてよい。OCCURS は使う分だけ並べれば残りは空白／ゼロになる。
   作ったら `check` で読み戻して確認する。
   `note: ... reads back as ...` は、読み戻すと別の文字になる文字（〜→～、－→− など）。照合テストで差分の原因になるので、ユーザーに伝える。

## 守ること

- 読めないバイトを推測で埋めない。`!` の行（パス・位置・バイト）をそのまま報告する。
- 元のデータファイルは上書きしない。`encode` の出力先は別のファイルにする。
- 本番データには個人情報が含まれることがある。必要な件数だけ読み、外部に送らない。
