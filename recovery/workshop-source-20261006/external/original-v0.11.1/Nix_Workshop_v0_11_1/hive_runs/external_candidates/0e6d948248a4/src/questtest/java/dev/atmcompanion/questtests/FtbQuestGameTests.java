package dev.atmcompanion.questtests;

import com.google.gson.GsonBuilder;
import com.mojang.authlib.GameProfile;
import dev.atmcompanion.integration.quest.OptionalQuestAccess;
import dev.atmcompanion.integration.quest.QuestService;
import dev.atmcompanion.integration.quest.QuestSnapshot;
import dev.atmcompanion.state.CapabilityStatus;
import dev.ftb.mods.ftbquests.api.FTBQuestsAPI;
import dev.ftb.mods.ftbquests.quest.BaseQuestFile;
import dev.ftb.mods.ftbquests.quest.Chapter;
import dev.ftb.mods.ftbquests.quest.Quest;
import dev.ftb.mods.ftbquests.quest.task.ItemTask;
import dev.ftb.mods.ftbteams.api.FTBTeamsAPI;
import dev.ftb.mods.ftbteams.api.property.TeamProperties;
import dev.ftb.mods.ftbteams.data.PlayerTeam;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Date;
import java.util.Optional;
import java.util.UUID;
import io.netty.channel.embedded.EmbeddedChannel;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.Connection;
import net.minecraft.network.protocol.PacketFlow;
import net.minecraft.server.level.ClientInformation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.CommonListenerCookie;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.neoforged.fml.ModList;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;
import net.neoforged.neoforge.network.registration.NetworkRegistry;

/** Real published FTB Quests/Teams/Library/Architectury, real server questfile and real team progress. */
@GameTestHolder("atm_companion_questtests")
@PrefixGameTestTemplate(false)
public final class FtbQuestGameTests {
    @GameTest(template = "empty", timeoutTicks = 200)
    public static void liveFtbTeamProgressAndDependencySemantics(GameTestHelper helper) throws Exception {
        helper.assertTrue(ModList.get().getModContainerById("ftbquests").orElseThrow().getModInfo().getVersion()
                .toString().equals(OptionalQuestAccess.SUPPORTED_VERSION), "Wrong real FTB binary loaded");
        var service = new QuestService();
        var synthetic = FakePlayerFactory.get(helper.getLevel(), new GameProfile(UUID.randomUUID(), "quest_synthetic"));
        helper.assertTrue(service.snapshot(synthetic).status() == CapabilityStatus.UNAVAILABLE,
                "Synthetic team progress was reported as known");
        helper.assertTrue(service.capability(synthetic).status() == CapabilityStatus.UNAVAILABLE,
                "Synthetic player received team readiness");
        helper.assertTrue(service.summary(synthetic).status() == CapabilityStatus.UNAVAILABLE,
                "Synthetic player received a known quest summary");

        var manager = FTBTeamsAPI.api().getManager();
        // Repair only the invalid 17-character profile made by an earlier version of THIS fixture.
        // Retaining the disposable world exercises repeat-run login against a populated quest book.
        for (var known : manager.getKnownPlayerTeams().values()) {
            if (known instanceof PlayerTeam oldFixture && oldFixture.getPlayerName().equals("quest-mock-player")) {
                oldFixture.setPlayerName("quest_fixture");
                oldFixture.setProperty(TeamProperties.DISPLAY_NAME, "quest_fixture");
                oldFixture.markDirty();
            }
        }
        int teamCount = manager.getTeams().size();
        var unmapped = new ServerPlayer(helper.getLevel().getServer(), helper.getLevel(),
                new GameProfile(UUID.randomUUID(), "unmapped_player"), ClientInformation.createDefault());
        helper.assertTrue(service.snapshot(unmapped).status() == CapabilityStatus.UNAVAILABLE,
                "Unresolved team was reported as known empty progression");
        helper.assertTrue(service.capability(unmapped).status() == CapabilityStatus.UNAVAILABLE,
                "Unresolved team received observation readiness");
        helper.assertTrue(service.summary(unmapped).status() == CapabilityStatus.UNAVAILABLE,
                "Unresolved team received a known quest summary");
        helper.assertTrue(manager.getTeams().size() == teamCount, "Read-only observation created an FTB team");

        var player = loggedInPlayer(helper);
        var team = manager.getTeamForPlayer(player).orElseThrow();
        BaseQuestFile file = FTBQuestsAPI.api().getQuestFile(false);
        var progress = file.getOrCreateTeamData(team);
        var chapter = new Chapter(file.newID(), file, file.getDefaultChapterGroup());
        chapter.onCreated();
        chapter.setRawTitle("Companion real FTB fixture");
        var first = quest(file, chapter, "First: diamonds", "all_completed");
        var second = quest(file, chapter, "Second: blocked until first", "all_completed");
        second.addDependency(first);
        var any = quest(file, chapter, "Either prerequisite", "one_completed");
        any.addDependency(first);
        any.addDependency(second);
        var firstTask = itemTask(file, first, Items.DIAMOND, 3);
        itemTask(file, second, Items.IRON_INGOT, 2);
        itemTask(file, any, Items.STICK, 1);
        file.clearCachedData();
        progress.setProgress(firstTask, 2);

        var before = requireAvailable(helper, service.snapshot(player));
        var beforeFirst = find(before, first);
        helper.assertTrue(before.progressScope().equals(QuestSnapshot.TEAM_SCOPE), "Completion scope is not explicit team scope");
        helper.assertTrue(before.chapters().stream().anyMatch(c -> c.id().equals(chapter.getCodeString())
                && c.title().equals("Companion real FTB fixture")), "Live chapter ID/title missing");
        helper.assertTrue(!beforeFirst.completed() && beforeFirst.tasks().getFirst().progress() == 2
                && beforeFirst.tasks().getFirst().maxProgress() == 3, "Live partial task progress mismatch");
        helper.assertTrue(beforeFirst.tasks().getFirst().itemReference().data().item().equals("minecraft:diamond"), "Item registry reference mismatch");
        helper.assertTrue(beforeFirst.tasks().getFirst().requirementRule().status() == CapabilityStatus.UNAVAILABLE,
                "Configured item reference was incorrectly promoted to a complete ingredient rule");
        helper.assertTrue(!find(before, second).dependenciesSatisfied() && !find(before, second).canStartTasks(),
                "Blocked FTB dependency claimed startable");
        helper.assertTrue(!before.availableQuestIds().contains(second.getCodeString()), "Blocked quest was listed as available");

        progress.setProgress(firstTask, 3);
        var after = requireAvailable(helper, service.snapshot(player));
        helper.assertTrue(find(after, first).completed() && find(after, first).tasks().getFirst().completed(),
                "Actual FTB task completion was not reflected");
        helper.assertTrue(!find(after, second).completed() && find(after, second).dependenciesSatisfied()
                && find(after, second).canStartTasks() && after.availableQuestIds().contains(second.getCodeString()),
                "FTB dependency completion did not unlock the second quest");
        helper.assertTrue(find(after, any).dependencies().size() == 2 && find(after, any).dependenciesSatisfied(),
                "FTB one_completed mode was incorrectly flattened to all_completed");
        helper.assertTrue(find(after, any).dependencyRule().status() == CapabilityStatus.UNAVAILABLE,
                "Unavailable dependency mode was fabricated");
        helper.assertTrue(after.quests().stream().map(QuestSnapshot.Quest::id).toList()
                .equals(after.quests().stream().map(QuestSnapshot.Quest::id).sorted().toList()), "Quest output is not deterministic by ID");

        progress.setLocked(true);
        var locked = requireAvailable(helper, service.snapshot(player));
        helper.assertTrue(locked.teamLocked() && locked.availableQuestIds().isEmpty(), "Locked team was given available quests");
        progress.setLocked(false);
        helper.assertTrue(service.summary(player).status() == CapabilityStatus.AVAILABLE,
                "Current personal team summary unavailable before party switch");

        // Change the team through FTB's actual party API. The observation must follow the current team.
        var party = manager.createPartyTeam(player, "CompanionFixture", null, null);
        var partyProgress = file.getOrCreateTeamData(party);
        partyProgress.setCompleted(second.getId(), new Date());
        var partySnapshot = requireAvailable(helper, service.snapshot(player));
        helper.assertTrue(find(partySnapshot, second).completed(), "Snapshot did not resolve the current FTB party team");
        var partySummary = service.summary(player);
        helper.assertTrue(partySummary.status() == CapabilityStatus.AVAILABLE
                && partySummary.data().completedQuests() == partySnapshot.quests().stream().filter(QuestSnapshot.Quest::completed).count()
                && partySummary.data().options().stream().map(dev.atmcompanion.integration.quest.QuestOverview.Option::id).toList()
                    .equals(partySnapshot.availableQuestIds().stream().limit(5).toList()),
                "Summary did not resolve current FTB party progression and options");

        Files.createDirectories(Path.of("evidence"));
        Files.writeString(Path.of("evidence/ftb-quests-fixture.json"), new GsonBuilder().setPrettyPrinting().create().toJson(partySnapshot));
        player.getServer().getPlayerList().remove(player);
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void wrongVersionGateNeverLinksAdapter(GameTestHelper helper) {
        var gate = new OptionalQuestAccess<Object>(() -> Optional.of("unsupported-version"),
                () -> { throw new AssertionError("Unsupported FTB version entered adapter factory"); }, ignored -> {});
        helper.assertTrue(gate.snapshot(new Object()).status() == CapabilityStatus.UNAVAILABLE, "Wrong version was treated as observed empty quests");
        helper.succeed();
    }

    private static Quest quest(BaseQuestFile file, Chapter chapter, String title, String dependencyMode) {
        var quest = new Quest(file.newID(), chapter);
        var config = new CompoundTag();
        config.putString("dependency_requirement", dependencyMode);
        config.putString("progression_mode", "linear");
        quest.readData(config, file.holderLookup());
        quest.onCreated();
        quest.setRawTitle(title);
        return quest;
    }
    private static ServerPlayer loggedInPlayer(GameTestHelper helper) {
        // Same embedded connection pattern as Mojang's GameTest helper, with NeoForge's official
        // mock negotiation BEFORE login: an existing quest book sends custom payloads during login.
        var server = helper.getLevel().getServer();
        var cookie = CommonListenerCookie.createInitial(new GameProfile(UUID.randomUUID(), "quest_fixture"), false);
        var player = new ServerPlayer(server, helper.getLevel(), cookie.gameProfile(), cookie.clientInformation());
        var connection = new Connection(PacketFlow.SERVERBOUND);
        new EmbeddedChannel(connection);
        NetworkRegistry.configureMockConnection(connection);
        server.getPlayerList().placeNewPlayer(connection, player, cookie);
        return player;
    }
    private static ItemTask itemTask(BaseQuestFile file, Quest quest, net.minecraft.world.item.Item item, int count) {
        var task = new ItemTask(file.newID(), quest).setStackAndCount(new ItemStack(item), count);
        task.onCreated();
        return task;
    }
    private static QuestSnapshot requireAvailable(GameTestHelper helper, dev.atmcompanion.state.Observation<QuestSnapshot> observation) {
        helper.assertTrue(observation.status() == CapabilityStatus.AVAILABLE, "Real FTB integration unavailable: " + observation.detail());
        return observation.data();
    }
    private static QuestSnapshot.Quest find(QuestSnapshot snapshot, Quest quest) {
        return snapshot.quests().stream().filter(q -> q.id().equals(quest.getCodeString())).findFirst().orElseThrow();
    }
}
