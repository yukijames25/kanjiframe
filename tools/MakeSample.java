// Build tests/data/custmast_930.dat independently of kanjiframe: text via the JDK's x-IBM930,
// numbers via this file's own packing code. Used as "a file from the mainframe" in tests and trials.
//
//   java tools/MakeSample.java tests/data/custmast_930.dat
import java.io.*;
import java.math.BigDecimal;
import java.nio.charset.Charset;

public class MakeSample {
    static final Charset CS = Charset.forName("x-IBM930");

    static byte[] text(String s, int len) {           // PIC X: mixed SBCS/DBCS with SO/SI, space padded
        byte[] b = s.getBytes(CS);
        if (b.length > len) throw new IllegalArgumentException(s);
        byte[] out = new byte[len];
        java.util.Arrays.fill(out, (byte) 0x40);
        System.arraycopy(b, 0, out, 0, b.length);
        return out;
    }

    static byte[] dbcs(String s, int chars) {          // PIC N: double-byte only (strip SO/SI)
        byte[] b = s.getBytes(CS);
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        for (byte x : b) if (x != 0x0E && x != 0x0F) o.write(x);
        byte[] d = o.toByteArray();
        byte[] out = new byte[chars * 2];
        for (int i = 0; i < out.length; i++) out[i] = 0x40;
        System.arraycopy(d, 0, out, 0, d.length);
        return out;
    }

    static byte[] zoned(long v, int len) {
        String s = String.format("%0" + len + "d", Math.abs(v));
        byte[] out = new byte[len];
        for (int i = 0; i < len; i++) out[i] = (byte) (0xF0 | (s.charAt(i) - '0'));
        return out;
    }

    static byte[] packed(String value, int len, int scale) {
        BigDecimal d = new BigDecimal(value).movePointRight(scale);
        String digits = d.abs().toBigIntegerExact().toString();
        int room = 2 * len - 1;
        StringBuilder s = new StringBuilder();
        for (int i = digits.length(); i < room; i++) s.append('0');
        s.append(digits).append(d.signum() < 0 ? 'D' : 'C');
        byte[] out = new byte[len];
        for (int i = 0; i < len; i++) out[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return out;
    }

    static byte[] bin4(int v) {
        return new byte[]{(byte) (v >> 24), (byte) (v >> 16), (byte) (v >> 8), (byte) v};
    }

    static void rec(OutputStream o, long no, String kana, String kanji, int y, int m, int d, String bal, int limit,
                    String branch, String[][] accts, String pref, String rest, String addrText, String status) throws IOException {
        ByteArrayOutputStream r = new ByteArrayOutputStream();
        r.write(zoned(no, 10));
        r.write(text(kana, 30));
        r.write(dbcs(kanji, 20));
        r.write(zoned(y, 4)); r.write(zoned(m, 2)); r.write(zoned(d, 2));
        r.write(packed(bal, 8, 2));
        r.write(bin4(limit));
        r.write(text(branch, 3));
        r.write(zoned(accts.length, 2));
        for (int i = 0; i < 3; i++) {
            if (i < accts.length) {
                r.write(text(accts[i][0], 2)); r.write(zoned(Long.parseLong(accts[i][1]), 7)); r.write(packed(accts[i][2], 7, 2));
            } else {
                r.write(text("", 2)); r.write(zoned(0, 7)); r.write(packed("0", 7, 2));
            }
        }
        if (addrText != null) r.write(text(addrText, 60));
        else { r.write(dbcs(pref, 4)); r.write(dbcs(rest, 26)); }
        r.write(text(status, 1));
        r.write(text("", 10));
        byte[] b = r.toByteArray();
        if (b.length != 224) throw new IllegalStateException("length " + b.length);
        o.write(b);
    }

    public static void main(String[] a) throws Exception {
        try (OutputStream o = new FileOutputStream(a[0])) {
            rec(o, 1000000001L, "ﾔﾏﾀﾞ ﾀﾛｳ", "山田太郎", 1985, 6, 15, "1234567.89", 500000, "101",
                new String[][]{{"01", "1111111", "1200000.00"}, {"02", "1111112", "34567.89"}}, "東京都", "千代田区丸の内１－１－１", null, "A");
            rec(o, 1000000002L, "ｽｽﾞｷ ﾊﾅｺ", "鈴木花子", 1990, 1, 2, "-3500.00", 100000, "205",
                new String[][]{{"01", "2222221", "-3500.00"}}, "大阪府", "大阪市北区梅田２丁目", null, "A");
            rec(o, 1000000003L, "ﾀｶﾊｼ ｹﾝ", "髙橋健", 1972, 11, 30, "98765.43", 0, "101",
                new String[][]{{"01", "3333331", "98765.43"}}, "北海道", "札幌市中央区北１条西２〜３", null, "C");
            rec(o, 1000000004L, "ABC ﾄﾚｰﾃﾞｨﾝｸﾞ", "ＡＢＣトレーディング", 2001, 4, 1, "0.00", 2000000, "310",
                new String[][]{}, null, null, "1-2-3 MARUNOUCHI CHIYODA-KU TOKYO", "A");
            rec(o, 1000000005L, "ｻﾄｳ ﾐｷ", "佐藤美紀", 1988, 9, 9, "250000.00", 300000, "205",
                new String[][]{{"01", "5555551", "250000.00"}, {"03", "5555552", "0.00"}, {"05", "5555553", "10.00"}}, "福岡県", "福岡市博多区博多駅前３－２", null, "A");
        }
        // damage record 5's BALANCE (offset 4*224 + 88): an invalid packed byte, as a bad transfer would
        try (RandomAccessFile f = new RandomAccessFile(a[0], "rw")) {
            f.seek(4 * 224 + 88 + 2);
            f.write(0x4A);
        }
        System.out.println("wrote " + a[0]);
    }
}
