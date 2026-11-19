---
title: "メインフレームの日本語データ（EBCDIC）を開発PCとAIで読み書きするツールを作った【依存ゼロ・MCP対応】"
emoji: "🗄️"
type: "tech"
topics: ["python", "cobol", "mainframe", "mcp", "claudecode"]
published: false
---

メインフレームの移行や保守の現場では、本番から抜いた固定長のデータを、コピーブック（COBOL のレコード定義）と一緒に受け取って、開発PCで中身を確かめる場面がよくあります。

ところが、日本語のデータになると急に手が止まります。カナや漢字が入った EBCDIC を読む手段が、手元に無いことが多いからです。そこで、**メインフレームの日本語データを、開発PCや AI エージェントから読み書きするツール** ebcdicjp を作りました。

https://github.com/yukijames25/ebcdicjp

## なぜ手元で読めないのか

- **Python に日本語 EBCDIC のコーデックが無い**：`b"...".decode("cp930")` は `LookupError: unknown encoding: cp930` になります。cp939 も同じです
- **欧米向けの手順では足りない**：ネットで見つかる手順の多くは英語の EBCDIC（cp037）向けです。日本語では、漢字の前後に入る SO（0E）/ SI（0F）、カナの入る IBM930 と英小文字の入る IBM939 の違い、SO/SI の無い PIC N（2バイト文字だけの項目）を扱う必要があります
- **数値がそのまま読めない**：金額はパック10進（COMP-3）、ゾーン10進、バイナリで入っていて、位置と長さはコピーブックを読まないと分かりません

結局、商用の変換製品か、ホスト側でテキストに変換してもらうのを待つことになります。

## できること

コピーブックから、各項目の位置（1始まり）・長さ・種類を出します。OCCURS は展開し、REDEFINES は同じ位置に並べます。

```
$ ebcdicjp layout CUSTMAST.cpy
CUST-REC  length=224
     1    10  zoned       CUST-REC.CUST-NO  9(10)
    11    30  text        CUST-REC.CUST-KANA  X(30)
    41    40  dbcs        CUST-REC.CUST-KANJI  N(20)
    89     8  packed  V2  CUST-REC.BALANCE  S9(13)V99
    97     4  binary      CUST-REC.CREDIT-LIMIT  S9(9)
   106     2  text        CUST-REC.ACCTS(1).ACCT-TYPE  X(2)
   115     7  packed  V2  CUST-REC.ACCTS(1).ACCT-BAL  S9(11)V99
   154    60  text        CUST-REC.ADDR-AREA  X(60)
   154     8  dbcs        CUST-REC.ADDR-JP.ADDR-PREF  N(4)
（抜粋）
```

データは JSONL・CSV・Markdown で読めます。コードページ（IBM930 / IBM939）、RDW（可変長レコードの先頭4バイト）の有無、コピーブックの文字コード（UTF-8 / Shift_JIS）はデータから判定し、**何を仮定したかを必ず表示します**。

```
$ ebcdicjp view CUST.dat -c CUSTMAST.cpy --format md -n 1 --use ADDR-JP
note: code page: IBM930 (IBM939 would read 22 bytes as lowercase letters with only 14% vowels — they look like half-width katakana, so IBM930); use --codepage to override
| CUST-KANA | ﾔﾏﾀﾞ ﾀﾛｳ |
| CUST-KANJI | 山田太郎 |
| BALANCE | 1234567.89 |
| ADDR-JP.ADDR-REST | 千代田区丸の内１−１−１ |
（抜粋）
```

ファイル全体の問題は、`check` で1行ずつ一覧にできます。どのレコードの（キー付き）、どの項目の、何バイト目の、どんなバイトがおかしいのかを出すので、そのまま客先への確認リストに使えます。

```
$ ebcdicjp check EMPMAST.dat -c EMPMAST.cpy --key EMP-ID
note: copybook is not UTF-8; read it as Shift_JIS (cp932)
note: assumed RDW variable-length records (6 records): ...
record 3  EMP-ID=E0000003  EMP-REC.ALLOWANCES(1).ALLOW-NAME  pos 92  [0E 46 50 ...]  bad-shift: ... (missing SI)
record 4  EMP-ID=E0000004  EMP-REC.EMP-NAME-KANJI  pos 13  [... 69 41 ...]  gaiji: user-defined character (外字) 6941
record 6  EMP-ID=E0000006  EMP-REC.DEPT-CD  pos 79  [C1 F1 C2 F2]  bad-number: byte 1 of the field (C1) is not a digit
```

テストデータも作れます。JSON（`view` の出力と同じ形）から、固定長または RDW 付きの EBCDIC ファイルを書き出します。

```
$ ebcdicjp text --encode "山田〜"
0E 45 65 45 63 43 A1 0F
! one-way (character 3): '〜' (U+301C) is stored as 43A1, which reads back as '～' (U+FF5E)
```

「〜」(U+301C) は 43A1 に変換されますが、読み戻すと「～」(U+FF5E) になります。こうした**戻らない文字（IBM930 で53種、IBM939 で54種）は書き込み時に知らせる**ので、移行後の照合テストで差分が出る理由が先に分かります。

ほかに扱えるもの：

- 項目の書き方：PIC X / N / G / 9 / S9 / V、COMP-3 / COMP / BINARY / DISPLAY-1、SIGN SEPARATE
- コピーブックの形：固定形式（1〜6桁目の連番、7桁目のコメント、73桁目以降）、OCCURS（DEPENDING ON は最大で配置）、REDEFINES
- レコード区分で読み方が変わるファイル：`--use HOJIN-DETAIL:TOR-KBN=1 --use KOJIN-DETAIL:TOR-KBN=2` で、法人と個人を1回で正しく読み分けます
- Python の codecs：`import ebcdicjp` のあとは `b"\x0e\x45\x65\x45\x63\x0f".decode("ibm930")` → `'山田'`

## 正しさは JDK と突き合わせた

変換表は、手元の JDK 21 にある `x-IBM930` / `x-IBM939` から生成しました。ネットから表をダウンロードしていません。テストでは次を JDK と突き合わせています。

- 2バイトの全コード（各 11,635 個）が、JDK と同じ文字になること
- 漢字・カナ・英数・半角カナを混ぜたランダムな 1,200 個の文字列が、JDK と**同じバイト列**（SO/SI の位置を含む）になること
- Java で独立に作ったデータファイルを正しく読めること

## 「利用者役のAI」に使わせて直した

テストが通っても、使う人が詰まらないとは限りません。そこで masume のときと同じく、**移行案件の SIer エンジニア役のエージェント**に README と手順書だけを渡し、上司の依頼（件数とコードページ、ある社員の給与と手当、データの問題すべて、テストデータ作成）をこなしてもらいました。データには、本人には知らせずに問題を仕込んであります。詰まった所を直して、また測り直しました。3回目は、直した所が別のデータでも効くかを見るため、新しいデータ（取引先マスタ）に替えています。

| 指標 | 1回目 | 2回目 | 3回目（新データ） |
|---|---|---|---|
| 依頼の正解 | 4 / 4 | 4 / 4 | 4 / 4 |
| ツールが示した仕込みの問題 | 3 / 4 | 4 / 4 | 3 / 3 |
| つまずき | 10件 | 3件 | 1件 |

答えは毎回正しかったのですが、1回目は**ツールのおかげではありませんでした**。

外字（ユーザー定義領域の文字）が、Unicode の私用領域の「見えない文字」に黙って変換され、ツールは「0 problem(s)」と答えていたのです。代役は、カナが「ｻﾄｳ ﾐｷ」なのに漢字が3文字しか見えないことに気づき、16進を読んで自力で見つけました。報告を信じていたら見落としていた、と書いてきました。今は外字を問題として報告し、値は「〓」で見せています。

2回目で見つかったのは、もっと怖いものでした。**英小文字の無い IBM939 のデータを、IBM930 と判定する**のです。カナが `iaqb jｯbn` のように化けたまま「0 problem(s)」・終了コード0で終わります。それまでの判定は英小文字の母音の割合に頼っていたので、メール欄が空のデータでは決め手がありませんでした。

調べると、IBM930 と IBM939 では半角カナの位置がずれていて、相手のカナの一部が英小文字に読めます。そこで「英小文字と半角カナが隣り合う」箇所（`tﾕnﾞ` のような並び）を数える判定を加えました。3回目の新しいデータ（カナだけで、英小文字が無い）では、正しく IBM939 と判定されています。それでも材料が足りないときは、黙らずに「code page UNCERTAIN」を出して、終了コード1にします。

ほかにも、使わせて初めて分かったことがありました。

- コピーブックが Shift_JIS だと `'utf-8' codec can't decode` で止まり、どうすればよいか分からない
- RDW 付きのファイルだと、39件の問題がずらりと並ぶだけで、原因を言わない
- エラーの位置が0始まりで、レイアウト表（1始まり）と1ずれる
- 法人と個人が混ざったファイルで REDEFINES を指定しないと、法人に「生年月日」の列が付いた CSV ができてしまう
- 読めなかった金額が CSV では空欄になり、「値が無い」のと区別できない（今は `#ERR`）

測った数字と、直したことの一覧は [docs/EVALUATION.md](https://github.com/yukijames25/ebcdicjp/blob/main/docs/EVALUATION.md) にあります。

## 推測で埋めないための工夫

- **読めないバイトを黙って置き換えない**：SO/SI の崩れ、割り当ての無いコード、数字でないパック10進などは、項目のパス（OCCURS の何番目かも）・位置・実際のバイトで報告します。SI が欠けているときは、漢字が始まった SO の位置を指します
- **仮定は必ず書く**：コードページ・RDW・コピーブックの文字コードを判定したら、`note:` に理由と一緒に出します。上書きのオプションも添えます
- **書き込みは別のファイルへ**：`encode` は元のファイルを上書きせず、桁あふれは切り詰めずにエラーで止めます。エラーには「何件目の、どの項目の、何桁目」かを出します
- **終了コードで判定できる**：0 = 問題なし、1 = 問題あり（またはコードページを決められない）、2 = エラー

Python 標準ライブラリだけで動きます（依存ゼロ・変換表を含めて約220KB）。MCP サーバーも、改行区切りの JSON-RPC を自前で実装しています。

## 使い方

```bash
pip install git+https://github.com/yukijames25/ebcdicjp
ebcdicjp layout CUSTMAST.cpy                            # 項目の位置と長さ
ebcdicjp view   CUST.dat -c CUSTMAST.cpy -n 5            # JSONL（--format csv / md も可）
ebcdicjp check  CUST.dat -c CUSTMAST.cpy --key CUST-NO   # 全件の問題を1行ずつ
ebcdicjp dump   CUST.dat -c CUSTMAST.cpy --skip 4 -n 1   # 5件目の項目ごとの16進と値
ebcdicjp detect CUST.dat -c CUSTMAST.cpy                 # IBM930 と IBM939 のどちらか
ebcdicjp encode records.jsonl -c CUSTMAST.cpy -o TEST.dat --codepage ibm930   # テストデータ
```

**Claude Code から使う**

```bash
claude mcp add ebcdicjp -- ebcdicjp-mcp
```

ツールは `describe_layout` / `read_records` / `write_records` / `decode_bytes` / `encode_text` / `detect_codepage` の6つです。リポジトリの `.claude/skills/ebcdicjp/` にはスキル（手順書）も入っています。note を必ず読んでユーザーに伝えること、読めないバイトを推測で埋めないこと、本番データを必要以上に読まないこと、などを書いてあります。

## できないこと

- 対応する文字コードは IBM930 / IBM939 です。KEIS（日立）・JEF（富士通）は、仕様を確かめてから対応する予定です
- 外字が何の字かは、各社の外字表が無いと分かりません。コード付きで報告するところまでです
- COMP-1 / COMP-2（浮動小数点）、RENAMES（66 レベル）、COPY 文の展開は未対応です
- コードページの判定は経験則です。材料が少ないデータでは「UNCERTAIN」になるので、`--codepage` で指定してください

## おわりに

まだ実際の利用者がいません。お手元のデータで試して、読み違いや分かりにくい表示があれば [Issue](https://github.com/yukijames25/ebcdicjp/issues) で教えてもらえるとうれしいです。本番データは添付せず、`ebcdicjp dump` の出力のうち問題の行だけ（個人情報を伏せて）を貼ってもらえると助かります。

https://github.com/yukijames25/ebcdicjp
