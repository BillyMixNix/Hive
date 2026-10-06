package dev.atmcompanion.state;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SnapshotFormatterUnicodeAcceptanceTest {
    private static void paired(String text) {
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (Character.isHighSurrogate(ch)) {
                assertTrue(i + 1 < text.length() && Character.isLowSurrogate(text.charAt(i + 1)));
                i++;
            } else assertFalse(Character.isLowSurrogate(ch));
        }
    }

    @Test void truncationNeverSplitsAPair() {
        String line = "a".repeat(SnapshotFormatter.MAX_LINE_CHARS - 4) + "\uD83D\uDE00" + "z".repeat(20);
        String result = SnapshotFormatter.boundLine(line);
        assertTrue(result.endsWith("..."));
        assertTrue(result.length() <= SnapshotFormatter.MAX_LINE_CHARS);
        paired(result);
    }

    @Test void fullPairAtExactBoundRemainsIntact() {
        String line = "a".repeat(SnapshotFormatter.MAX_LINE_CHARS - 2) + "\uD83D\uDE00";
        assertEquals(line, SnapshotFormatter.boundLine(line));
    }

    @Test void asciiAndSanitizationStayCompatible() {
        assertEquals("one?two?three", SnapshotFormatter.boundLine("one\ntwo\u00a7three"));
        assertEquals("a".repeat(237) + "...", SnapshotFormatter.boundLine("a".repeat(260)));
    }
}
