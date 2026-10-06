package dev.atmcompanion.questtests;

import com.google.gson.GsonBuilder;
import com.mojang.authlib.GameProfile;
import dev.atmcompanion.integration.quest.QuestService;
import dev.atmcompanion.integration.quest.QuestSnapshot;
import dev.atmcompanion.integration.quest.QuestOverview;
import dev.atmcompanion.state.CapabilityStatus;
import dev.atmcompanion.state.Observation;
import dev.ftb.mods.ftbquests.api.FTBQuestsAPI;
import dev.ftb.mods.ftbquests.quest.BaseQuestFile;
import dev.ftb.mods.ftbquests.quest.Chapter;
import dev.ftb.mods.ftbquests.quest.Quest;
import dev.ftb.mods.ftbquests.quest.task.ItemTask;
import dev.ftb.mods.ftbteams.api.FTBTeamsAPI;
import io.netty.channel.embedded.EmbeddedChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.Connection;
import net.minecraft.network.protocol.PacketFlow;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.CommonListenerCookie;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;
import net.neoforged.neoforge.network.registration.NetworkRegistry;

/** Generated public-API fixture; no copied pack definitions and no player-world data. */
@GameTestHolder("atm_companion_questtests")
@PrefixGameTestTemplate(false)
public final class LargeFtbQuestGameTests {
    private static final int QUESTS = 4790;
    private static final int CHAPTERS = 66;
    private static final Path EVIDENCE = Path.of("evidence/ftb-large-book.json");

    @GameTest(template = "empty", batch = "large_ftb_book", timeoutTicks = 400)
    public static void largeBookFirstObservationAndLiveFreshness(GameTestHelper helper) throws Exception {
        var evidence = new LinkedHashMap<String, Object>();
        evidence.put("fixture", "generated real FTB definitions, not the actual ATM10 quest book");
        evidence.put("fixtureQuests", QUESTS);
        evidence.put("fixtureChapters", CHAPTERS);
        evidence.put("fixtureTasks", QUESTS * 2);
        evidence.put("note", "Cold summary runs before any full observation of the new definitions. Full samples follow summary; no claim that cold full export always succeeds.");
        var samples = new ArrayList<Map<String, Object>>();
        evidence.put("observations", samples);
        var summaries = new ArrayList<Map<String, Object>>();
        evidence.put("summaries", summaries);
        BaseQuestFile file = FTBQuestsAPI.api().getQuestFile(false);
        var chapters = new ArrayList<Chapter>();
        var quests = new ArrayList<Quest>();
        var firstTasks = new ArrayList<ItemTask>();
        var secondTasks = new ArrayList<ItemTask>();
        var titlesToRestore = new java.util.IdentityHashMap<Quest, String>();
        var player = loggedInPlayer(helper);
        var team = FTBTeamsAPI.api().getManager().getTeamForPlayer(player).orElseThrow();
        var progress = file.getOrCreateTeamData(team);
        int originalChapters = file.getAllChapters().size();
        int originalQuests = file.getAllChapters().stream().mapToInt(c -> c.getQuests().size()).sum();
        evidence.put("existingChapters", originalChapters);
        evidence.put("existingQuests", originalQuests);
        try {
            long setupStarted = System.nanoTime();
            for (int c = 0; c < CHAPTERS; c++) {
                var chapter = new Chapter(file.newID(), file, file.getDefaultChapterGroup());
                chapter.onCreated();
                chapter.setRawTitle("Companion disposable scale chapter " + c);
                chapters.add(chapter);
            }
            Quest previous = null;
            for (int i = 0; i < QUESTS; i++) {
                var quest = new Quest(file.newID(), chapters.get(i * CHAPTERS / QUESTS));
                var config = new CompoundTag();
                config.putString("dependency_requirement", "all_completed");
                config.putString("progression_mode", "linear");
                quest.readData(config, file.holderLookup());
                quest.onCreated();
                quest.setRawTitle("Collect ingredients for the next machine — fixture " + i);
                // Separate chains of at most eight: realistic dependency work without recursive path explosions.
                if (i % 8 != 0) quest.addDependency(previous);
                var first = new ItemTask(file.newID(), quest).setStackAndCount(new ItemStack(Items.DIAMOND), 3);
                first.onCreated();
                var second = new ItemTask(file.newID(), quest).setStackAndCount(new ItemStack(Items.IRON_INGOT), 2);
                second.onCreated();
                quests.add(quest);
                firstTasks.add(first);
                secondTasks.add(second);
                previous = quest;
            }
            file.clearCachedData();
            evidence.put("definitionSetupMillis", millisSince(setupStarted));
            var service = new QuestService();
            var coldSummary = measureSummary(service, player, "cold_before_full_observations", summaries);
            write(evidence);
            var summary = availableSummary(helper, coldSummary);
            var initial = new ArrayList<Observation<QuestSnapshot>>();
            // Record all attempts before assertions, so a pre-fix timeout leaves useful baseline evidence.
            for (int i = 0; i < 4; i++) initial.add(measure(service, player, "initial_" + i, samples));
            var successful = initial.stream().filter(o -> o.status() == CapabilityStatus.AVAILABLE).findFirst();
            if (successful.isPresent()) {
                long serializationStarted = System.nanoTime();
                byte[] json = new GsonBuilder().create().toJson(successful.get().data()).getBytes(StandardCharsets.UTF_8);
                evidence.put("serializedSnapshotBytes", json.length);
                evidence.put("serializationMillis", millisSince(serializationStarted));
            }
            write(evidence);
            for (int i = 0; i < initial.size(); i++) {
                var observation = initial.get(i);
                if (observation.status() != CapabilityStatus.AVAILABLE) {
                    helper.assertTrue(observation.data() == null,
                            "Timed out detailed collection exposed partial data as a snapshot");
                    continue;
                }
                helper.assertTrue(observation.data().quests().size() == originalQuests + QUESTS,
                        "Large book was silently truncated");
                helper.assertTrue(observation.data().chapters().size() == originalChapters + CHAPTERS,
                        "Large book chapter count mismatch");
            }
            helper.assertTrue(successful.isPresent(), "No complete detailed observation succeeded after four bounded attempts");
            assertSummaryMatchesFull(helper, summary, successful.orElseThrow().data());
            long readinessStarted = System.nanoTime();
            var readiness = service.capability(player);
            evidence.put("readinessMillis", millisSince(readinessStarted));
            evidence.put("readinessDetail", readiness.detail());
            helper.assertTrue(readiness.status() == CapabilityStatus.AVAILABLE
                    && readiness.detail().contains("not collected"),
                    "Readiness capability implied a successful full-book observation");

            // All subsequent edits occur in this same server tick; stale snapshot reuse would fail.
            var targetQuest = quests.getFirst();
            var targetTask = firstTasks.getFirst();
            progress.setProgress(targetTask, 2);
            var partial = available(helper, measure(service, player, "progress_change", samples));
            helper.assertTrue(find(partial, targetQuest).tasks().stream()
                    .anyMatch(t -> t.id().equals(targetTask.getCodeString()) && t.progress() == 2 && !t.completed()),
                    "Large-book snapshot retained stale task progress");
            var partialSummary = availableSummary(helper, measureSummary(service, player, "partial_progress", summaries));
            assertSummaryMatchesFull(helper, partialSummary, partial);
            progress.setProgress(targetTask, 3);
            progress.setProgress(secondTasks.getFirst(), 2);
            var completedSummary = availableSummary(helper, measureSummary(service, player, "completion_change", summaries));
            var completed = available(helper, measure(service, player, "completion_change", samples));
            helper.assertTrue(find(completed, targetQuest).completed(), "Fixture task completion did not complete real FTB quest");
            helper.assertTrue(completedSummary.completedQuests() == partialSummary.completedQuests() + 1,
                    "Summary retained stale same-tick completion counts");
            assertSummaryMatchesFull(helper, completedSummary, completed);
            progress.setLocked(true);
            var lockedSummary = availableSummary(helper, measureSummary(service, player, "team_lock", summaries));
            var locked = available(helper, measure(service, player, "team_lock", samples));
            helper.assertTrue(locked.teamLocked() && locked.availableQuestIds().isEmpty(),
                    "Large-book snapshot retained available quests for a locked team");
            assertSummaryMatchesFull(helper, lockedSummary, locked);
            progress.setLocked(false);

            // Change an actually selected available option, so summary title freshness is observable.
            var beforeDefinition = availableSummary(helper, measureSummary(service, player, "unlocked", summaries));
            String selectedId = beforeDefinition.options().getFirst().id();
            var selected = file.getAllChapters().stream().flatMap(c -> c.getQuests().stream())
                    .filter(q -> q.getCodeString().equals(selectedId)).findFirst().orElseThrow();
            String originalTitle = selected.getRawTitle();
            titlesToRestore.put(selected, originalTitle);
            selected.setRawTitle("Definition replaced in the same tick");
            var removed = quests.removeLast();
            removed.deleteSelf();
            file.clearCachedData();
            var changedSummary = availableSummary(helper, measureSummary(service, player, "definition_change", summaries));
            var changed = detailedAfterDefinitionInvalidation(helper, service, player, samples);
            selected.setRawTitle(originalTitle);
            file.clearCachedData();
            helper.assertTrue(find(changed, selected).title().equals("Definition replaced in the same tick")
                    && changed.quests().size() == originalQuests + QUESTS - 1
                    && changed.quests().stream().noneMatch(q -> q.id().equals(removed.getCodeString())),
                    "Large-book snapshot retained stale definitions");
            helper.assertTrue(changedSummary.options().stream().anyMatch(o -> o.id().equals(selectedId)
                    && o.title().equals("Definition replaced in the same tick")), "Summary retained stale option title");
            assertSummaryMatchesFull(helper, changedSummary, changed);
            evidence.put("sameTickProgressLockAndDefinitionFreshness", true);
            evidence.put("status", "passed");
            write(evidence);
        } finally {
            titlesToRestore.forEach(Quest::setRawTitle);
            // Public deletion recursively removes only definitions created by this fixture.
            for (var chapter : chapters) chapter.deleteSelf();
            file.clearCachedData();
            progress.setLocked(false);
            player.getServer().getPlayerList().remove(player);
            evidence.put("remainingChapters", file.getAllChapters().size());
            evidence.put("remainingQuests", file.getAllChapters().stream().mapToInt(c -> c.getQuests().size()).sum());
            evidence.putIfAbsent("status", "failed_before_all_assertions");
            write(evidence);
        }
        helper.assertTrue(file.getAllChapters().size() == originalChapters
                && file.getAllChapters().stream().mapToInt(c -> c.getQuests().size()).sum() == originalQuests,
                "Scale fixture did not clean up its own definitions");
        helper.succeed();
    }

    private static Observation<QuestSnapshot> measure(QuestService service, ServerPlayer player, String label,
            List<Map<String, Object>> samples) {
        long started = System.nanoTime();
        var observation = service.snapshot(player);
        var sample = new LinkedHashMap<String, Object>();
        sample.put("label", label);
        sample.put("elapsedMillis", millisSince(started));
        sample.put("status", observation.status().toString());
        sample.put("detail", observation.detail());
        if (observation.data() != null) {
            sample.put("quests", observation.data().quests().size());
            sample.put("tasks", observation.data().quests().stream().mapToInt(q -> q.tasks().size()).sum());
            sample.put("availableQuests", observation.data().availableQuestIds().size());
        }
        samples.add(sample);
        return observation;
    }

    private static QuestSnapshot available(GameTestHelper helper, Observation<QuestSnapshot> observation) {
        helper.assertTrue(observation.status() == CapabilityStatus.AVAILABLE,
                "Large real FTB observation unavailable: " + observation.detail());
        return observation.data();
    }

    private static QuestSnapshot detailedAfterDefinitionInvalidation(GameTestHelper helper, QuestService service,
            ServerPlayer player, List<Map<String, Object>> samples) {
        // clearCachedData invalidates FTB's expensive task-title cache. The complete debug projection
        // still truthfully permits a cold timeout; keep each attempt bounded and expose no partial data.
        // No tick or progress/definition change occurs between these fixture-only attempts.
        for (int attempt = 0; attempt < 4; attempt++) {
            var observation = measure(service, player, "definition_change_attempt_" + attempt, samples);
            if (observation.status() == CapabilityStatus.AVAILABLE) return observation.data();
            helper.assertTrue(observation.data() == null, "Timed out full projection returned partial quest data");
        }
        helper.fail("No fresh complete detailed snapshot succeeded after four bounded attempts following definition invalidation");
        throw new AssertionError("GameTest helper failed to terminate failed test");
    }

    private static Observation<QuestOverview> measureSummary(QuestService service, ServerPlayer player, String label,
            List<Map<String, Object>> samples) {
        long started = System.nanoTime();
        var observation = service.summary(player);
        var sample = new LinkedHashMap<String, Object>();
        sample.put("label", label);
        sample.put("elapsedMillis", millisSince(started));
        sample.put("status", observation.status().toString());
        sample.put("detail", observation.detail());
        if (observation.data() != null) {
            sample.put("quests", observation.data().questCount());
            sample.put("completed", observation.data().completedQuests());
            sample.put("available", observation.data().availableQuests());
            sample.put("options", observation.data().options().size());
        }
        samples.add(sample);
        return observation;
    }

    private static QuestOverview availableSummary(GameTestHelper helper, Observation<QuestOverview> observation) {
        helper.assertTrue(observation.status() == CapabilityStatus.AVAILABLE,
                "Large real FTB summary unavailable: " + observation.detail());
        return observation.data();
    }

    private static void assertSummaryMatchesFull(GameTestHelper helper, QuestOverview overview, QuestSnapshot full) {
        helper.assertTrue(overview.chapterCount() == full.chapters().size() && overview.questCount() == full.quests().size()
                && overview.completedQuests() == full.quests().stream().filter(QuestSnapshot.Quest::completed).count()
                && overview.availableQuests() == full.availableQuestIds().size() && overview.teamLocked() == full.teamLocked(),
                "Summary aggregate flags differ from complete real FTB snapshot");
        helper.assertTrue(overview.options().stream().map(QuestOverview.Option::id).toList()
                .equals(full.availableQuestIds().stream().limit(5).toList()),
                "Summary options are not exactly the first five available quests");
        for (var option : overview.options()) {
            var quest = full.quests().stream().filter(q -> q.id().equals(option.id())).findFirst().orElseThrow();
            helper.assertTrue(option.chapterId().equals(quest.chapterId()) && option.title().equals(quest.title()),
                    "Summary option altered observed identity or title");
        }
    }

    private static QuestSnapshot.Quest find(QuestSnapshot snapshot, Quest quest) {
        return snapshot.quests().stream().filter(q -> q.id().equals(quest.getCodeString())).findFirst().orElseThrow();
    }

    private static double millisSince(long started) { return (System.nanoTime() - started) / 1_000_000.0; }

    private static void write(Map<String, Object> evidence) throws Exception {
        Files.createDirectories(EVIDENCE.getParent());
        Files.writeString(EVIDENCE, new GsonBuilder().setPrettyPrinting().create().toJson(evidence));
    }

    private static ServerPlayer loggedInPlayer(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var cookie = CommonListenerCookie.createInitial(new GameProfile(UUID.randomUUID(), "quest_scale"), false);
        var player = new ServerPlayer(server, helper.getLevel(), cookie.gameProfile(), cookie.clientInformation());
        var connection = new Connection(PacketFlow.SERVERBOUND);
        new EmbeddedChannel(connection);
        NetworkRegistry.configureMockConnection(connection);
        server.getPlayerList().placeNewPlayer(connection, player, cookie);
        return player;
    }
}
