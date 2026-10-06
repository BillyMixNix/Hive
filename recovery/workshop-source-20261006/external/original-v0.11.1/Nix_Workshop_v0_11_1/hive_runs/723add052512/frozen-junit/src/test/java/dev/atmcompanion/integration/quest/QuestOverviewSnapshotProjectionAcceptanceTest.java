package dev.atmcompanion.integration.quest;

import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class QuestOverviewSnapshotProjectionAcceptanceTest {
    private QuestSnapshot.Quest quest(int id, String chapter, String title,
                                      boolean visible, boolean completed, boolean canStart) {
        String questId = String.format(java.util.Locale.ROOT, "%016X", id);
        return new QuestSnapshot.Quest(questId, chapter, title, visible, false, completed, canStart,
                false, false, List.of(), Observation.unavailable("Dependency semantics not exported"), List.of());
    }

    private QuestSnapshot snapshot(boolean locked) {
        String visibleChapter = "0000000000000001";
        String hiddenChapter = "0000000000000002";
        var chapters = List.of(
                new QuestSnapshot.Chapter(visibleChapter, "Visible", true, false, false),
                new QuestSnapshot.Chapter(hiddenChapter, "Hidden", false, false, false));
        var quests = new java.util.ArrayList<QuestSnapshot.Quest>();
        quests.add(quest(10, visibleChapter, "Completed", true, true, false));
        for (int id = 11; id <= 16; id++) quests.add(quest(id, visibleChapter, "Available " + id, true, false, true));
        quests.add(quest(17, hiddenChapter, "Hidden chapter quest", true, false, true));
        var available = locked ? List.<String>of() : java.util.stream.IntStream.rangeClosed(11, 16)
                .mapToObj(id -> String.format(java.util.Locale.ROOT, "%016X", id)).toList();
        return new QuestSnapshot(1, "2026-09-30T11:59:00Z", OptionalQuestAccess.SUPPORTED_VERSION,
                QuestSnapshot.TEAM_SCOPE, locked, chapters, quests, available, QuestSnapshot.AVAILABILITY_RULE);
    }

    @Test
    void projectsCountsAndSortedCappedOptionsWithoutInferringHiddenAvailability() {
        var source = snapshot(false);
        var overview = QuestOverview.fromSnapshot(source, "2026-09-30T12:00:00Z");

        assertEquals("2026-09-30T12:00:00Z", overview.timestamp());
        assertEquals(source.sourceVersion(), overview.sourceVersion());
        assertEquals(QuestSnapshot.TEAM_SCOPE, overview.progressScope());
        assertFalse(overview.teamLocked());
        assertEquals(2, overview.chapterCount());
        assertEquals(8, overview.questCount());
        assertEquals(1, overview.completedQuests());
        assertEquals(6, overview.availableQuests());
        assertEquals(QuestOverview.MAX_OPTIONS, overview.options().size());
        assertEquals(List.of("000000000000000B", "000000000000000C", "000000000000000D",
                        "000000000000000E", "000000000000000F"),
                overview.options().stream().map(QuestOverview.Option::id).toList());
        assertEquals("Available 11", overview.options().getFirst().title());
        assertTrue(overview.options().stream().allMatch(o -> o.chapterId().equals("0000000000000001")));
        assertEquals(QuestSnapshot.AVAILABILITY_RULE, overview.availabilityRule());
        assertEquals(QuestOverview.OMITTED_DETAILS, overview.detail());

        var locked = QuestOverview.fromSnapshot(snapshot(true), "2026-09-30T12:00:00Z");
        assertTrue(locked.teamLocked());
        assertEquals(0, locked.availableQuests());
        assertTrue(locked.options().isEmpty());
    }
}
