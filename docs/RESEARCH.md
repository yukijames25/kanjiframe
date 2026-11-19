# 調査メモ：ebcdicjp を選んだ理由（2026-11-19）

## 進め方（masume の反省から）

1. 使う人の困りごとから出発する
2. 作る前に、実物で確かめる
3. 使われるところまで見届ける（今回はポートフォリオどまり。代役の利用者テストで測る）

## 候補と判定

| 候補 | 困りごと | 競合（GitHub・製品） | 判定 |
|---|---|---|---|
| 全銀フォーマットの振込ファイル作成・検証 | 口座名義の半角カナ・法人略語「カ)」でエラーや組戻し | GitHub に生成・検証ツールが約15件（いずれも小規模）、Go のライブラリ、銀行コードのデータ集 | 混んでいる |
| 入金消込（振込名義カナ ⇔ 請求先の漢字名） | 名義の表記揺れで消込が手作業に戻る | SaaS 多数、今月だけでもデモの公開リポジトリが5件、振込名義カナの整形ツールも先週公開 | 混んでいる |
| **日本語メインフレームデータ（EBCDIC のカナ・漢字）の読み書き** | 移行・テストで、IBM930/939・KEIS・JEF の固定長データを読めない／確かめられない | **GitHub にほぼ無し**（cp930/cp939/KEIS/JEF で検索してもヒットなし）。変換は日立・NEC などの**商用製品**。AWS の Python 手順は欧米のコードページ（cp037）だけ | **空白地帯** |

## 作る前に確かめたこと

- **Python の標準ライブラリでは読めない**：`cp930` `cp939` はコーデックとして存在しない（`LookupError`）。
  IBM930 で作った「山田太郎」のレコードを cp037・Shift_JIS・EUC-JP で読むと、すべて文字化けした。
- **正解を手元で作れる**：この PC の JDK 21 に `x-IBM930` `x-IBM939` `IBM290` `x-IBM300` がある。
  ダウンロードなしで、変換表の生成と全コードの突き合わせができる。
- **実際に起きる落とし穴を確認**：Java で「１－１」を IBM930 に変換して戻すと「１−１」（U+2212）になる。
  「－」「〜」「￢」などの対応の違いは、移行で文字化けや差分が出る典型的な原因。

## 想定する利用者

- メインフレーム移行・保守の現場のエンジニア（SIer、金融・保険・官公庁系）
  - 本番から抜いた固定長データ（コピーブック付き）を、開発PCで読みたい・照合したい
  - テストデータを EBCDIC で作りたい
- COBOL のモダナイゼーションを手伝う AI エージェント（Claude Code など）
  - データセットの中身を読めないと、変換プログラムの正しさを確かめられない

## 作るもの（最小構成）

1. コーデック：IBM930 / IBM939（SO/SI でのシフト、カナ／英小文字の違い）。Python の `codecs` に登録して `bytes.decode("ibm930")` で使える
2. 数値：パック10進（COMP-3）、ゾーン10進（符号付き）、バイナリ（COMP）
3. COBOL コピーブックの解析（PIC X / N / 9 / S9、COMP-3、OCCURS、REDEFINES、FILLER）
4. 固定長レコードの表示・JSON/CSV 出力、逆方向（JSON → 固定長）
5. CLI と MCP サーバー（AI エージェントから使う）
6. 文字の対応の違い（「－」「〜」など）を、黙って変えずに報告する

KEIS・JEF は、仕様を資料で確かめてから次の段階で扱う。

## 参考

- [AWS: Convert and unpack EBCDIC data to ASCII on AWS by using Python](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/convert-and-unpack-ebcdic-data-to-ascii-on-aws-by-using-python.html)（欧米のコードページのみ）
- [日立 コード変換 FAQ](https://www.hitachi.co.jp/Prod/comp/soft1/codecnv/info/faq/index.html)（JEF・KEIS のシフトコードの違い、外字）
- [NEC EDIAI Server 機能](https://jpn.nec.com/ediaiserver/function02.html)（商用の変換製品の例）
- [bakuraku: 入金消込の課題](https://bakuraku.jp/knowledge/knowledge-ar-management/reconciliation/)（候補比較用）
- GitHub 検索（2026-11-19）: `zengin` `全銀` `入金消込` `振込名義` `cp930` `cp939` `KEIS JEF` `ebcdic japanese`
