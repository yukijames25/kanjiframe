// Dump IBM930 / IBM939 mappings from the JDK's charsets (the reference implementation).
//
//   java tools/GenTables.java local/
//
// Writes <charset>.tsv with lines:
//   S <byte hex> <unicode hex>          single-byte decode
//   D <2-byte hex> <unicode hex>        double-byte decode (between SO 0x0E and SI 0x0F)
//   E <unicode hex> <1|2-byte hex>      encode (includes one-way mappings the decoder never produces)
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.*;
import java.nio.file.*;
import java.util.*;

public class GenTables {
    public static void main(String[] args) throws Exception {
        Path out = Paths.get(args.length > 0 ? args[0] : "local");
        Files.createDirectories(out);
        for (String name : new String[]{"x-IBM930", "x-IBM939"}) {
            Charset cs = Charset.forName(name);
            List<String> lines = new ArrayList<>();
            for (int b = 0; b < 256; b++) {
                if (b == 0x0E || b == 0x0F) continue;
                String s = decode(cs, new byte[]{(byte) b});
                if (s != null && s.length() == 1) lines.add(String.format("S %02X %04X", b, (int) s.charAt(0)));
            }
            for (int b1 = 0x40; b1 <= 0xFE; b1++) {
                for (int b2 = 0x40; b2 <= 0xFE; b2++) {
                    String s = decode(cs, new byte[]{0x0E, (byte) b1, (byte) b2, 0x0F});
                    if (s != null && s.length() == 1) lines.add(String.format("D %02X%02X %04X", b1, b2, (int) s.charAt(0)));
                }
            }
            CharsetEncoder enc = cs.newEncoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT);
            for (int cp = 0; cp < 0x10000; cp++) {
                if (cp >= 0xD800 && cp <= 0xDFFF) continue;
                enc.reset();
                ByteBuffer bb;
                try {
                    bb = enc.encode(CharBuffer.wrap(new char[]{(char) cp}));
                } catch (CharacterCodingException e) {
                    continue;
                }
                byte[] r = new byte[bb.remaining()];
                bb.get(r);
                StringBuilder hx = new StringBuilder();
                for (byte x : r) {
                    int v = x & 0xFF;
                    if (v == 0x0E || v == 0x0F) continue; // shift codes are added by the encoder state
                    hx.append(String.format("%02X", v));
                }
                lines.add(String.format("E %04X %s", cp, hx));
            }
            Files.write(out.resolve(name.replace("x-", "").toLowerCase() + ".tsv"), lines);
            System.out.println(name + ": " + lines.size() + " lines");
        }
    }

    static String decode(Charset cs, byte[] b) {
        CharsetDecoder dec = cs.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT);
        try {
            return dec.decode(ByteBuffer.wrap(b)).toString();
        } catch (CharacterCodingException e) {
            return null;
        }
    }
}
