import java.lang.reflect.Method;
import java.util.Random;

/** Supplemental black-box checks; runs the real compiled formatter via reflection. */
public final class BoundLineSupplementalProbe {
    private static final int CAP = 240;
    private static final int PREFIX_BUDGET = 237;
    private static final String FACE = new String(Character.toChars(0x1F642));
    private static Method boundLine;
    private static int checks;

    public static void main(String[] args) throws Exception {
        Class<?> formatter = Class.forName("dev.atmcompanion.state.SnapshotFormatter");
        boundLine = formatter.getMethod("boundLine", String.class);
        require(formatter.getField("MAX_LINE_CHARS").getInt(null) == CAP,
                "MAX_LINE_CHARS remains 240");
        System.out.println("SUPPLEMENTAL probe target=" + formatter.getName());
        System.out.println("Compiled class origin=" + formatter.getProtectionDomain().getCodeSource());

        expect("ASCII empty", "", "");
        expect("ASCII below", "a".repeat(239), "a".repeat(239));
        expect("ASCII exact", "a".repeat(240), "a".repeat(240));
        expect("ASCII above", "a".repeat(241), "a".repeat(237) + "...");
        expect("ASCII very long", "a".repeat(10_000), "a".repeat(237) + "...");
        for (int length = 0; length <= 600; length++) {
            verifyAgainstContract("ASCII length " + length, "z".repeat(length));
        }

        expect("pair before cutoff", "a".repeat(235) + FACE + "z".repeat(20),
                "a".repeat(235) + FACE + "...");
        expect("pair intersects cutoff", "a".repeat(236) + FACE + "z".repeat(20),
                "a".repeat(236) + "...");
        expect("pair after cutoff", "a".repeat(237) + FACE + "z".repeat(20),
                "a".repeat(237) + "...");
        expect("pair just after cutoff", "a".repeat(238) + FACE + "z".repeat(20),
                "a".repeat(237) + "...");
        expect("pair fits exact cap", "a".repeat(238) + FACE,
                "a".repeat(238) + FACE);
        expect("pair within short input", "a".repeat(236) + FACE,
                "a".repeat(236) + FACE);
        expect("supplementary only exact cap", FACE.repeat(120), FACE.repeat(120));
        expect("supplementary only truncated", FACE.repeat(121), FACE.repeat(118) + "...");

        expect("control before intersecting pair", "a".repeat(235) + "\n" + FACE + "z".repeat(20),
                "a".repeat(235) + "?...");
        expect("section before intersecting pair", "a".repeat(235) + "\u00a7" + FACE + "z".repeat(20),
                "a".repeat(235) + "?...");
        expect("pair before replaced cutoff character", "a".repeat(234) + FACE + "\t" + "z".repeat(20),
                "a".repeat(234) + FACE + "?...");
        expect("pair before section cutoff character", "a".repeat(234) + FACE + "\u00a7" + "z".repeat(20),
                "a".repeat(234) + FACE + "?...");
        expect("replacement after cutoff excluded", "a".repeat(237) + "\n\u00a7" + "z".repeat(20),
                "a".repeat(237) + "...");
        expect("control and section at exact cap", "a".repeat(237) + "\n\u00a7\u007f",
                "a".repeat(237) + "???");
        expect("original regex C1 behavior", "A\u0080\u0085\u009fB\u00a7C",
                "A\u0080\u0085\u009fB?C");
        for (int c = 0; c <= 31; c++) {
            expect("ASCII control U+" + Integer.toHexString(c), "a" + (char) c + "b", "a?b");
        }
        expect("DEL replacement", "a\u007fb", "a?b");

        // Every position around the cutoff is exercised with both endpoint and random supplementary code points.
        int[] supplementary = {0x10000, 0x1F642, 0x20000, 0x10FFFF};
        for (int cp : supplementary) {
            for (int offset = 232; offset <= 242; offset++) {
                verifyAgainstContract("supplementary U+" + Integer.toHexString(cp) + " at " + offset,
                        "p".repeat(offset) + new String(Character.toChars(cp)) + "q".repeat(20));
            }
        }

        long seed = 0x4A3030315F555446L;
        Random random = new Random(seed);
        for (int trial = 0; trial < 10_000; trial++) {
            int codePointCount = random.nextInt(420);
            StringBuilder input = new StringBuilder();
            for (int index = 0; index < codePointCount; index++) {
                int kind = random.nextInt(8);
                int cp;
                if (kind <= 2) cp = 'a' + random.nextInt(26);
                else if (kind == 3) cp = 0x10000 + random.nextInt(0x100000);
                else if (kind == 4) cp = random.nextBoolean() ? random.nextInt(32) : 0x7F;
                else if (kind == 5) cp = 0xA7;
                else {
                    do { cp = random.nextInt(0x10000); } while (cp >= 0xD800 && cp <= 0xDFFF);
                }
                input.appendCodePoint(cp);
            }
            verifyAgainstContract("seeded Unicode trial " + trial, input.toString());
        }
        System.out.println("PASS " + checks + " supplemental cases; random seed=" + seed);
        System.out.println("Coverage: ASCII, cutoff pair positions, sanitization, UTF-16 cap, valid surrogate structure, 10000 seeded Unicode inputs.");
    }

    private static void expect(String label, String input, String expected) throws Exception {
        require(wellFormed(input), label + ": probe input must be well-formed UTF-16");
        String actual = (String) boundLine.invoke(null, input);
        require(expected.equals(actual), label + ": expected=" + escaped(expected) + " actual=" + escaped(actual));
        require(actual.length() <= CAP, label + ": output exceeds UTF-16 cap");
        require(wellFormed(actual), label + ": output contains an unpaired surrogate");
        checks++;
    }

    private static void verifyAgainstContract(String label, String input) throws Exception {
        // Independent code-point oracle: sanitize tokens, then fit whole tokens into the prefix budget.
        int[] tokens = input.codePoints().map(cp -> cp < 32 || cp == 127 || cp == 0xA7 ? '?' : cp).toArray();
        int units = 0;
        for (int cp : tokens) units += Character.charCount(cp);
        boolean truncated = units > CAP;
        int available = truncated ? PREFIX_BUDGET : CAP;
        StringBuilder expected = new StringBuilder();
        for (int cp : tokens) {
            int needed = Character.charCount(cp);
            if (needed > available) break;
            expected.appendCodePoint(cp);
            available -= needed;
        }
        if (truncated) expected.append("...");
        expect(label, input, expected.toString());
    }

    private static boolean wellFormed(String text) {
        for (int i = 0; i < text.length(); i++) {
            char current = text.charAt(i);
            if (Character.isHighSurrogate(current)) {
                if (++i >= text.length() || !Character.isLowSurrogate(text.charAt(i))) return false;
            } else if (Character.isLowSurrogate(current)) return false;
        }
        return true;
    }

    private static String escaped(String text) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c >= 32 && c <= 126) result.append(c);
            else result.append(String.format("\\u%04x", (int) c));
        }
        return result.toString();
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
