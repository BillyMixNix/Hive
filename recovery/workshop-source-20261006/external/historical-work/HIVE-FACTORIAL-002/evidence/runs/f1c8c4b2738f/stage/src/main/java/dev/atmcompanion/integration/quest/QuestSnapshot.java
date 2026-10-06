package dev.atmcompanion.integration.quest;

import dev.atmcompanion.state.Observation;
import java.util.List;
import java.util.Objects;
import java.util.regex.Pattern;

/** Server-side FTB team observations. IDs are FTB's unsigned 16-digit hexadecimal codes. */
public record QuestSnapshot(int schemaVersion, String timestamp, String sourceVersion,
        String progressScope, boolean teamLocked, List<Chapter> chapters, List<Quest> quests,
        List<String> availableQuestIds, String availabilityRule) {
    public static final int SCHEMA_VERSION = 1;
    public static final int MAX_CHAPTERS = 256;
    public static final int MAX_QUESTS = 8192;
    public static final int MAX_TASKS_PER_QUEST = 64;
    public static final int MAX_DEPENDENCIES_PER_QUEST = 256;
    public static final int MAX_TEXT_LENGTH = 256;
    public static final String TEAM_SCOPE = "current_player_ftb_team";
    public static final String AVAILABILITY_RULE = "chapter_visible_and_quest_visible_and_team_unlocked_and_ftb_can_start_tasks_and_not_completed";
    private static final Pattern OBJECT_ID = Pattern.compile("[0-9A-F]{16}");
    private static final Pattern REGISTRY_ID = Pattern.compile("[a-z0-9_.-]+:[a-z0-9/._-]+");

    public QuestSnapshot {
        if (schemaVersion != SCHEMA_VERSION) throw new IllegalArgumentException("Unsupported quest schema");
        Objects.requireNonNull(timestamp); java.time.Instant.parse(timestamp);
        text(sourceVersion);
        if (!TEAM_SCOPE.equals(progressScope)) throw new IllegalArgumentException("Unsupported progress scope");
        if (!AVAILABILITY_RULE.equals(availabilityRule)) throw new IllegalArgumentException("Unsupported availability rule");
        chapters = bounded(chapters, MAX_CHAPTERS);
        quests = bounded(quests, MAX_QUESTS);
        availableQuestIds = bounded(availableQuestIds, MAX_QUESTS);
        availableQuestIds.forEach(QuestSnapshot::id);
        var visibleChapters = chapters.stream().filter(Chapter::visible).map(Chapter::id).collect(java.util.stream.Collectors.toSet());
        var expected = quests.stream().filter(q -> visibleChapters.contains(q.chapterId())
                        && !teamLocked && q.visible() && q.canStartTasks() && !q.completed())
                .map(Quest::id).sorted().toList();
        if (!availableQuestIds.equals(expected)) throw new IllegalArgumentException("Available quests contradict observed flags");
    }

    public record Chapter(String id, String title, boolean visible, boolean started, boolean completed) {
        public Chapter { QuestSnapshot.id(id); text(title); }
    }

    public record Quest(String id, String chapterId, String title, boolean visible, boolean started,
            boolean completed, boolean canStartTasks, boolean dependenciesSatisfied, boolean repeatable,
            List<Dependency> dependencies, Observation<String> dependencyRule, List<Task> tasks) {
        public Quest {
            QuestSnapshot.id(id); QuestSnapshot.id(chapterId); text(title);
            dependencies = bounded(dependencies, MAX_DEPENDENCIES_PER_QUEST);
            Objects.requireNonNull(dependencyRule);
            tasks = bounded(tasks, MAX_TASKS_PER_QUEST);
        }
    }

    public record Dependency(String id, String objectType) {
        public Dependency { QuestSnapshot.id(id); text(objectType); }
    }

    public record Task(String id, String type, String title, long progress, long maxProgress,
            boolean started, boolean completed, boolean consumesResources,
            Observation<ItemReference> itemReference, Observation<String> requirementRule) {
        public Task {
            QuestSnapshot.id(id); registryId(type); text(title);
            if (progress < 0 || maxProgress < 0) throw new IllegalArgumentException("Negative task progress");
            Objects.requireNonNull(itemReference); Objects.requireNonNull(requirementRule);
        }
    }

    /** A configured display/reference item, never a claim that this fully specifies item matching. */
    public record ItemReference(String item, boolean hasComponentPatch) {
        public ItemReference { registryId(item); }
    }

    static void id(String id) {
        if (id == null || !OBJECT_ID.matcher(id).matches()) throw new IllegalArgumentException("Invalid FTB quest ID");
    }
    private static void registryId(String id) {
        if (id == null || id.length() > MAX_TEXT_LENGTH || !REGISTRY_ID.matcher(id).matches())
            throw new IllegalArgumentException("Invalid registry ID");
    }
    static void text(String text) {
        if (text == null || text.length() > MAX_TEXT_LENGTH) throw new IllegalArgumentException("Unbounded/null quest text");
    }
    private static <T> List<T> bounded(List<T> values, int limit) {
        if (values == null || values.size() > limit) throw new IllegalArgumentException("Quest collection exceeds bound");
        return List.copyOf(values);
    }
}
