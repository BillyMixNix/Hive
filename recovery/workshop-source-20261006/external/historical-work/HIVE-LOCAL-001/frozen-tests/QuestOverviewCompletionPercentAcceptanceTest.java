package dev.atmcompanion.integration.quest;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class QuestOverviewCompletionPercentAcceptanceTest {
    private QuestOverview overview(int total, int completed, int available, boolean locked) {
        var options = java.util.stream.IntStream.range(0, Math.min(QuestOverview.MAX_OPTIONS, available))
                .mapToObj(i -> new QuestOverview.Option(String.format(java.util.Locale.ROOT, "%016X", i + 1),
                        "0000000000000001", "Quest " + i)).toList();
        return new QuestOverview(1, "2026-09-30T12:00:00Z", OptionalQuestAccess.SUPPORTED_VERSION,
                QuestSnapshot.TEAM_SCOPE, locked, 1, total, completed, available, options,
                QuestSnapshot.AVAILABILITY_RULE, QuestOverview.OMITTED_DETAILS);
    }

    @Test
    void usesAllQuestsRatherThanAvailableQuestsAndHandlesZero() {
        assertEquals(30, overview(10, 3, 2, false).completionPercent());
        assertEquals(0, overview(0, 0, 0, true).completionPercent());
        assertEquals(99, overview(QuestSnapshot.MAX_QUESTS, QuestSnapshot.MAX_QUESTS - 1,
                0, false).completionPercent());
        assertEquals(100, overview(10, 10, 0, true).completionPercent());
    }
}
