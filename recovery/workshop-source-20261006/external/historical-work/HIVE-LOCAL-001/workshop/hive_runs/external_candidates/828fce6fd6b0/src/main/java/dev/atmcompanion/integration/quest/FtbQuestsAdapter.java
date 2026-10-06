package dev.atmcompanion.integration.quest;

import com.mojang.logging.LogUtils;
import dev.atmcompanion.state.Capability;
import dev.atmcompanion.state.CapabilityStatus;
import dev.atmcompanion.state.Observation;
import dev.atmcompanion.state.SnapshotService;
import dev.ftb.mods.ftbquests.api.FTBQuestsAPI;
import dev.ftb.mods.ftbquests.quest.BaseQuestFile;
import dev.ftb.mods.ftbquests.quest.Chapter;
import dev.ftb.mods.ftbquests.quest.Quest;
import dev.ftb.mods.ftbquests.quest.QuestObjectBase;
import dev.ftb.mods.ftbquests.quest.TeamData;
import dev.ftb.mods.ftbquests.quest.task.ItemTask;
import dev.ftb.mods.ftbquests.quest.task.Task;
import dev.ftb.mods.ftbteams.api.FTBTeamsAPI;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;

/** Typed optional adapter for the pinned release. Instantiated only after the lazy version gate. */
final class FtbQuestsAdapter {
    private static final int MAX_GROUPS = 256;
    private static final int MAX_TOTAL_TASKS = 16384;
    private static final int MAX_TOTAL_DEPENDENCIES = 32768;
    private static final long MAX_COLLECTION_NANOS = 250_000_000L;
    // Unsigned numeric order equals fixed-width uppercase hexadecimal order, without formatting on every comparison.
    private static final Comparator<QuestObjectBase> BY_ID = (left, right) -> Long.compareUnsigned(left.getId(), right.getId());
    // These immutable statements describe adapter limits, never a player's mutable state.
    private static final Observation<String> DEPENDENCY_RULE = Observation.unavailable(
            "Dependency mode has no public getter in the supported FTB release; use dependenciesSatisfied");
    private static final Observation<String> TASK_RULE = Observation.unavailable(
            "Task-specific matching, filters, components and submission rules are not integrated; itemReference is not a fixed ingredient");
    private static final Observation<QuestSnapshot.ItemReference> NO_ITEM_REFERENCE = Observation.unavailable(
            "This task type has no integrated item reference");
    private static final Observation<QuestSnapshot.ItemReference> EMPTY_ITEM_REFERENCE = Observation.unavailable(
            "Item task has no configured item reference");

    private record Context(BaseQuestFile file, TeamData progress) {}

    /** Readiness is distinct from collecting or successfully validating the full quest book. */
    static Capability capability(ServerPlayer player) {
        var context = context(player);
        return context.data() == null ? Capability.from(context) : new Capability(CapabilityStatus.AVAILABLE,
                "FTB APIs and current team progression are ready; quest book and progress details were not collected by this readiness probe");
    }

    private static Observation<Context> context(ServerPlayer player) {
        SnapshotService.requireServerThread(player);
        if (player.isFakePlayer()) return Observation.unavailable("Synthetic players do not have persistent FTB team progression");
        var file = FTBQuestsAPI.api().getQuestFile(false);
        if (file == null || !file.isServerSide() || file.isLoading())
            return Observation.unavailable("FTB server quest file is not ready");
        var teams = FTBTeamsAPI.api();
        if (teams == null || !teams.isManagerLoaded())
            return Observation.unavailable("FTB Teams manager is not ready");
        var manager = teams.getManager();
        if (manager.getServer() != player.getServer())
            return Observation.unavailable("FTB team manager does not belong to the player's server");
        var team = manager.getTeamForPlayer(player);
        if (team.isEmpty()) return Observation.unavailable("No current FTB team could be resolved for this player");
        // Do not call getTeamData(player)/getOrCreateTeamData: observation must not manufacture progress.
        TeamData progress = file.getNullableTeamData(team.get().getId());
        if (progress == null) return Observation.unavailable("FTB has no recorded progression for the current team");
        return Observation.available(new Context(file, progress));
    }

    Observation<QuestSnapshot> snapshot(ServerPlayer player) {
        var timing = new CollectionTiming("full");
        try {
            var context = context(player);
            if (context.data() == null) {
                timing.outcome = "unavailable";
                return new Observation<>(context.status(), null, context.detail());
            }
            var file = context.data().file();
            var progress = context.data().progress();
            timing.phase(1);
            var chapters = new ArrayList<Chapter>();
            var quests = new ArrayList<Quest>();
            if (file.getChapterGroups().size() > MAX_GROUPS) return timing.tooLarge();
            for (var group : file.getChapterGroups()) {
                if (chapters.size() + group.getChapters().size() > QuestSnapshot.MAX_CHAPTERS) return timing.tooLarge();
                chapters.addAll(group.getChapters());
            }
            int totalTasks = 0;
            for (var chapter : chapters) {
                if (quests.size() + chapter.getQuests().size() > QuestSnapshot.MAX_QUESTS) return timing.tooLarge();
                quests.addAll(chapter.getQuests());
            }
            for (var quest : quests) {
                if (quest.getTasks().size() > QuestSnapshot.MAX_TASKS_PER_QUEST) return timing.tooLarge();
                totalTasks += quest.getTasks().size();
                if (totalTasks > MAX_TOTAL_TASKS) return timing.tooLarge();
            }
            timing.expectedChapters = chapters.size();
            timing.expectedQuests = quests.size();
            timing.expectedTasks = totalTasks;
            chapters.sort(BY_ID);
            quests.sort(BY_ID);
            timing.phase(2);
            var chapterDtos = new ArrayList<QuestSnapshot.Chapter>(chapters.size());
            for (var chapter : chapters) {
                if (timing.expired()) return timing.timedOut();
                chapterDtos.add(new QuestSnapshot.Chapter(QuestIds.format(chapter.getId()), title(chapter),
                        chapter.isVisible(progress), progress.isStarted(chapter), progress.isCompleted(chapter)));
                timing.collectedChapters++;
            }
            timing.phase(3);
            var questDtos = new ArrayList<QuestSnapshot.Quest>(quests.size());
            int totalDependencies = 0;
            for (var quest : quests) {
                if (timing.expired()) return timing.timedOut();
                var dependencies = quest.streamDependencies().limit(QuestSnapshot.MAX_DEPENDENCIES_PER_QUEST + 1L)
                        .sorted(BY_ID).map(d -> new QuestSnapshot.Dependency(QuestIds.format(d.getId()), d.getObjectType().getId())).toList();
                totalDependencies += dependencies.size();
                timing.dependencies = totalDependencies;
                if (dependencies.size() > QuestSnapshot.MAX_DEPENDENCIES_PER_QUEST || totalDependencies > MAX_TOTAL_DEPENDENCIES)
                    return timing.tooLarge();
                List<Task> tasks = new ArrayList<>(quest.getTasks());
                tasks.sort(BY_ID);
                var taskDtos = new ArrayList<QuestSnapshot.Task>(tasks.size());
                for (var task : tasks) {
                    if (timing.expired()) return timing.timedOut();
                    taskDtos.add(task(task, progress));
                    timing.collectedTasks++;
                }
                questDtos.add(new QuestSnapshot.Quest(QuestIds.format(quest.getId()), QuestIds.format(quest.getChapter().getId()),
                        title(quest), quest.isVisible(progress), progress.isStarted(quest), progress.isCompleted(quest),
                        progress.canStartTasks(quest), progress.areDependenciesComplete(quest), quest.canBeRepeated(),
                        dependencies, DEPENDENCY_RULE, taskDtos));
                timing.collectedQuests++;
            }
            if (timing.expired()) return timing.timedOut();
            timing.phase(4);
            boolean locked = progress.isLocked();
            var visibleChapters = chapterDtos.stream().filter(QuestSnapshot.Chapter::visible)
                    .map(QuestSnapshot.Chapter::id).collect(java.util.stream.Collectors.toSet());
            var available = questDtos.stream().filter(q -> visibleChapters.contains(q.chapterId())
                            && !locked && q.visible() && q.canStartTasks() && !q.completed())
                    .map(QuestSnapshot.Quest::id).toList();
            var snapshot = new QuestSnapshot(QuestSnapshot.SCHEMA_VERSION, Instant.now().toString(),
                    OptionalQuestAccess.SUPPORTED_VERSION, QuestSnapshot.TEAM_SCOPE, locked,
                    chapterDtos, questDtos, available, QuestSnapshot.AVAILABILITY_RULE);
            // Include final immutable copies and schema validation in the cooperative budget too.
            if (timing.expired()) return timing.timedOut();
            timing.outcome = "available";
            return Observation.available(snapshot);
        } finally {
            timing.log();
        }
    }

    /** Fresh same-thread counts/options. Expensive task/title/detail extraction is intentionally excluded. */
    static Observation<QuestOverview> summary(ServerPlayer player) {
        var timing = new CollectionTiming("summary");
        try {
            var context = context(player);
            if (context.data() == null) {
                timing.outcome = "unavailable";
                return new Observation<>(context.status(), null, context.detail());
            }
            var file = context.data().file();
            var progress = context.data().progress();
            timing.phase(1);
            var chapters = new ArrayList<Chapter>();
            var quests = new ArrayList<Quest>();
            if (file.getChapterGroups().size() > MAX_GROUPS) return timing.tooLarge();
            for (var group : file.getChapterGroups()) {
                if (timing.expired()) return timing.timedOut();
                if (chapters.size() + group.getChapters().size() > QuestSnapshot.MAX_CHAPTERS)
                    return timing.tooLarge();
                chapters.addAll(group.getChapters());
            }
            for (var chapter : chapters) {
                if (timing.expired()) return timing.timedOut();
                if (quests.size() + chapter.getQuests().size() > QuestSnapshot.MAX_QUESTS)
                    return timing.tooLarge();
                quests.addAll(chapter.getQuests());
            }
            timing.expectedChapters = chapters.size();
            timing.expectedQuests = quests.size();
            // A stable first five requires only IDs, not all quest titles or task details.
            quests.sort(BY_ID);
            timing.phase(2);
            var visibleChapters = new HashSet<Long>();
            for (var chapter : chapters) {
                if (timing.expired()) return timing.timedOut();
                if (chapter.isVisible(progress)) visibleChapters.add(chapter.getId());
                timing.collectedChapters++;
            }
            timing.phase(3);
            boolean locked = progress.isLocked();
            int completed = 0;
            int available = 0;
            var options = new ArrayList<QuestOverview.Option>(QuestOverview.MAX_OPTIONS);
            for (var quest : quests) {
                if (timing.expired()) return timing.timedOut();
                boolean isCompleted = progress.isCompleted(quest);
                if (isCompleted) completed++;
                if (!locked && !isCompleted && visibleChapters.contains(quest.getChapter().getId())
                        && quest.isVisible(progress) && progress.canStartTasks(quest)) {
                    available++;
                    if (options.size() < QuestOverview.MAX_OPTIONS)
                        options.add(new QuestOverview.Option(QuestIds.format(quest.getId()),
                                QuestIds.format(quest.getChapter().getId()), title(quest)));
                }
                timing.collectedQuests++;
            }
            timing.phase(4);
            var overview = new QuestOverview(QuestOverview.SCHEMA_VERSION, Instant.now().toString(),
                    OptionalQuestAccess.SUPPORTED_VERSION, QuestSnapshot.TEAM_SCOPE, locked,
                    chapters.size(), quests.size(), completed, available, options,
                    QuestSnapshot.AVAILABILITY_RULE, QuestOverview.OMITTED_DETAILS);
            if (timing.expired()) return timing.timedOut();
            timing.outcome = "available";
            return Observation.available(overview);
        } finally {
            timing.log();
        }
    }

    private static QuestSnapshot.Task task(Task task, TeamData progress) {
        Observation<QuestSnapshot.ItemReference> reference = NO_ITEM_REFERENCE;
        // Exact class only: custom subclasses may reinterpret the configured stack.
        if (task.getClass() == ItemTask.class) {
            var stack = ((ItemTask) task).getItemStack();
            if (!stack.isEmpty()) {
                reference = Observation.available(new QuestSnapshot.ItemReference(
                        BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), !stack.isComponentsPatchEmpty()));
            } else {
                reference = EMPTY_ITEM_REFERENCE;
            }
        }
        return new QuestSnapshot.Task(QuestIds.format(task.getId()), task.getType().getTypeId().toString(), title(task),
                progress.getProgress(task), task.getMaxProgress(), progress.isStarted(task), progress.isCompleted(task),
                task.consumesResources(), reference, TASK_RULE);
    }

    private static String title(QuestObjectBase object) {
        String title = object.getTitle().getString();
        return title.length() <= QuestSnapshot.MAX_TEXT_LENGTH ? title : title.substring(0, QuestSnapshot.MAX_TEXT_LENGTH - 1) + "…";
    }
    /** Fixed-size diagnostics only: no player identity, quest title or progress contents enter the log. */
    private static final class CollectionTiming {
        private static final String[] PHASES = {"readiness", "definitions", "chapters", "quests_tasks", "validation"};
        private final long started = System.nanoTime();
        private final String mode;
        private final long[] elapsed = new long[PHASES.length];
        private long phaseStarted = started;
        private int phase;
        private int expectedChapters, expectedQuests, expectedTasks;
        private int collectedChapters, collectedQuests, collectedTasks, dependencies;
        private String outcome = "failed";

        CollectionTiming(String mode) { this.mode = mode; }

        void phase(int next) {
            long now = System.nanoTime();
            elapsed[phase] += now - phaseStarted;
            phaseStarted = now;
            phase = next;
        }
        boolean expired() { return System.nanoTime() - started > MAX_COLLECTION_NANOS; }
        <T> Observation<T> tooLarge() {
            outcome = "limit";
            return Observation.unavailable("FTB quest definition exceeds bounded snapshot limits; no partial quest state is reported as complete");
        }
        <T> Observation<T> timedOut() {
            outcome = "timed_out";
            return Observation.unavailable("FTB quest " + mode + " observation exceeded the cooperative 250 ms collection budget during "
                    + PHASES[phase] + "; see server log for bounded phase timings");
        }
        void log() {
            long ended = System.nanoTime();
            elapsed[phase] += ended - phaseStarted;
            LogUtils.getLogger().info("ATM Companion FTB observation mode={} outcome={} chapters={}/{} quests={}/{} tasks={}/{} dependencies={} "
                            + "readinessMs={} definitionsMs={} chaptersMs={} questsTasksMs={} validationMs={} totalMs={}",
                    mode, outcome, collectedChapters, expectedChapters, collectedQuests, expectedQuests,
                    collectedTasks, expectedTasks, dependencies, elapsed[0] / 1_000_000.0,
                    elapsed[1] / 1_000_000.0, elapsed[2] / 1_000_000.0, elapsed[3] / 1_000_000.0,
                    elapsed[4] / 1_000_000.0, (ended - started) / 1_000_000.0);
        }
    }
}
