package dev.atmcompanion.state;

import org.junit.jupiter.api.Test;

import java.util.Locale;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;

class SnapshotFormatterTest {
    @Test
    void fullInventoryIsSummarizedWithStrictChatBounds() {
        var items = IntStream.range(0, GameSnapshot.MAX_INVENTORY_SLOTS)
                .mapToObj(slot -> new GameSnapshot.Item("example:" + "a".repeat(500) + slot, 64, slot, false))
                .toList();
        var lines = SnapshotFormatter.state(SnapshotFixtures.withInventory(items));

        assertTrue(lines.size() <= SnapshotFormatter.MAX_STATE_LINES);
        assertTrue(lines.stream().allMatch(line -> line.length() <= SnapshotFormatter.MAX_LINE_CHARS));
        assertTrue(lines.stream().anyMatch(line -> line.contains("+ 61 other stacks")));
        assertEquals(3, lines.stream().filter(line -> line.contains("64 x example:")).count());
    }

    @Test
    void unknownInventoryAndProgressionAreNeverFormattedAsKnownZero() {
        String summary = String.join("\n", SnapshotFormatter.state(SnapshotFixtures.unavailable()));

        assertTrue(summary.contains("Inventory: unavailable"));
        assertTrue(summary.contains("Advancements: unavailable"));
        assertFalse(summary.contains("0 occupied"));
        assertFalse(summary.contains("0 completed"));
    }

    @Test
    void inspectedEmptyInventoryIsClearlyDifferentFromUnavailable() {
        String summary = String.join("\n", SnapshotFormatter.state(SnapshotFixtures.empty()));

        assertTrue(summary.contains("Inventory: 0 occupied slots"));
        assertTrue(summary.contains("Main hand: empty"));
        assertFalse(summary.contains("Inventory: unavailable"));
    }

    @Test
    void chatTextCannotInjectNewLinesOrMinecraftFormatting() {
        String result = SnapshotFormatter.boundLine("title\nline\r\t\u0000\u00a7cRed");

        assertFalse(result.chars().anyMatch(c -> Character.isISOControl(c) || c == '\u00a7'));
        assertTrue(result.contains("Red"));
    }

    @Test
    void locationNumbersHaveStableFormattingAcrossHostLocales() {
        Locale previous = Locale.getDefault();
        try {
            Locale.setDefault(Locale.FRANCE);
            String summary = String.join("\n", SnapshotFormatter.state(SnapshotFixtures.empty()));
            assertTrue(summary.contains("XYZ: 183.3 / 72.0 / -491.8"));
        } finally {
            Locale.setDefault(previous);
        }
    }
}
