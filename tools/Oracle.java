// Reference encoder/decoder for tests: the JDK's x-IBM930 / x-IBM939.
//
//   java tools/Oracle.java enc x-IBM930 < lines.txt   (each line: code points as hex, space separated)
//   java tools/Oracle.java dec x-IBM930 < lines.txt   (each line: bytes as hex)
//
// Output: one line per input line, hex bytes (enc) or code points as hex (dec), or "ERR".
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.*;

public class Oracle {
    public static void main(String[] a) throws Exception {
        Charset cs = Charset.forName(a[1]);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "US-ASCII"));
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "US-ASCII");
        String line;
        while ((line = in.readLine()) != null) {
            line = line.trim();
            try {
                if (a[0].equals("enc")) {
                    StringBuilder s = new StringBuilder();
                    if (!line.isEmpty()) for (String h : line.split(" ")) s.appendCodePoint(Integer.parseInt(h, 16));
                    CharsetEncoder e = cs.newEncoder().onUnmappableCharacter(CodingErrorAction.REPORT).onMalformedInput(CodingErrorAction.REPORT);
                    ByteBuffer bb = e.encode(CharBuffer.wrap(s));
                    StringBuilder hx = new StringBuilder();
                    while (bb.hasRemaining()) hx.append(String.format("%02X", bb.get() & 0xFF));
                    out.println(hx);
                } else {
                    byte[] b = new byte[line.length() / 2];
                    for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(line.substring(2 * i, 2 * i + 2), 16);
                    CharsetDecoder d = cs.newDecoder().onUnmappableCharacter(CodingErrorAction.REPORT).onMalformedInput(CodingErrorAction.REPORT);
                    String s = d.decode(ByteBuffer.wrap(b)).toString();
                    StringBuilder hx = new StringBuilder();
                    s.codePoints().forEach(cp -> hx.append(String.format("%04X ", cp)));
                    out.println(hx.toString().trim());
                }
            } catch (CharacterCodingException ex) {
                out.println("ERR");
            }
        }
    }
}
