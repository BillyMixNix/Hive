package dev.atmcompanion.integration.quest;

import dev.atmcompanion.state.Observation;
import java.util.List;

final class QuestFixtures {
    static final String CHAPTER_ID = "0000000000000001";
    private QuestFixtures() {}

    static QuestSnapshot empty() { return snapshot(List.of(), List.of(), false); }

    static QuestSnapshot snapshot(List<QuestSnapshot.Quest> quests, List<String> available, boolean locked) {
        return new QuestSnapshot(1, "2026-09-22T12:34:56Z", OptionalQuestAccess.SUPPORTED_VERSION,
                QuestSnapshot.TEAM_SCOPE, locked, List.of(new QuestSnapshot.Chapter(CHAPTER_ID, "Chapter", true, false, false)),
                quests, available, QuestSnapshot.AVAILABILITY_RULE);
    }

    static QuestSnapshot.Quest quest(String id, boolean visible, boolean complete, boolean canStart) {
        return new QuestSnapshot.Quest(id, CHAPTER_ID, "Quest", visible, false, complete, canStart, false, false,
                List.of(), Observation.unavailable("Dependency operator not inspected"), List.of());
    }
}
