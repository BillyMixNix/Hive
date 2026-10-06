package dev.atmcompanion.integration.quest;

import java.util.Locale;
import java.util.Random;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class QuestIdsTest {
    @Test
    void formatterPreservesFtbUnsignedFixedWidthCodesAcrossSignedBoundaries() {
        for (long id : new long[]{0, 1, 15, 16, Long.MAX_VALUE, Long.MIN_VALUE, -1, -16}) {
            assertEquals(String.format(Locale.ROOT, "%016X", id), QuestIds.format(id));
        }
        var random = new Random(4790);
        for (int i = 0; i < 256; i++) {
            long id = random.nextLong();
            assertEquals(String.format(Locale.ROOT, "%016X", id), QuestIds.format(id));
        }
    }
}
