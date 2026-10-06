package dev.atmcompanion.integration.quest;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** A fresh count/option projection, not a complete quest or task graph. */
public record QuestOverview(int schemaVersion, String timestamp, String sourceVersion,
        String progressScope, boolean teamLocked, int chapterCount, int questCount,
        int completedQuests, int availableQuests, List<Option> options,
        String availabilityRule, String detail) {
    public static final int SCHEMA_VERSION = 1;
    public static final int MAX_OPTIONS = 5;
    public static final String OMITTED_DETAILS =
            "Current quest counts and up to five available options only; task progress, dependencies and full quest details were not collected";

    public QuestOverview {
        if (schemaVersion != SCHEMA_VERSION) throw new IllegalArgumentException("Unsupported quest overview schema");
        Instant.parse(Objects.requireNonNull(timestamp));
        QuestSnapshot.text(sourceVersion);
        if (!QuestSnapshot.TEAM_SCOPE.equals(progressScope)
                || !QuestSnapshot.AVAILABILITY_RULE.equals(availabilityRule)
                || !OMITTED_DETAILS.equals(detail)) throw new IllegalArgumentException("Unsupported quest overview semantics");
        if (chapterCount < 0 || chapterCount > QuestSnapshot.MAX_CHAPTERS
                || questCount < 0 || questCount > QuestSnapshot.MAX_QUESTS
                || completedQuests < 0 || completedQuests > questCount
                || availableQuests < 0 || availableQuests > questCount - completedQuests
                || teamLocked && availableQuests != 0)
            throw new IllegalArgumentException("Contradictory quest overview counts");
        Objects.requireNonNull(options);
        if (options.size() != Math.min(MAX_OPTIONS, availableQuests))
            throw new IllegalArgumentException("Quest options do not match the bounded projection");
        options = List.copyOf(options);
        String previous = null;
        for (var option : options) {
            if (previous != null && previous.compareTo(option.id()) >= 0)
                throw new IllegalArgumentException("Quest options must have unique sorted IDs");
            previous = option.id();
        }
    }

    public int completionPercent() {
        return questCount == 0 ? 0 : (int) (100L * completedQuests / questCount);
    }

    public record Option(String id, String chapterId, String title) {
        public Option { QuestSnapshot.id(id); QuestSnapshot.id(chapterId); QuestSnapshot.text(title); }
    }
}
