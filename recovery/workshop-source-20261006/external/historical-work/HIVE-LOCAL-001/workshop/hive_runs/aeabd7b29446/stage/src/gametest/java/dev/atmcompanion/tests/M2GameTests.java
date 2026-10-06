package dev.atmcompanion.tests;

import com.mojang.authlib.GameProfile;
import dev.atmcompanion.knowledge.RecipeIndex;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import dev.atmcompanion.planning.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;
import net.minecraft.SharedConstants;
import net.minecraft.commands.CommandSource;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.NbtAccounter;
import net.minecraft.nbt.NbtIo;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.packs.PackType;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.storage.LevelResource;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.event.OnDatapackSyncEvent;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;

@GameTestHolder("atm_companion_tests")
@PrefixGameTestTemplate(false)
public final class M2GameTests {
    private static ServerPlayer player(GameTestHelper helper, String name) {
        var p = FakePlayerFactory.get(helper.getLevel(), new GameProfile(UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)), name));
        p.getInventory().clearContent();
        return p;
    }
    @GameTest(template = "empty")
    @SuppressWarnings("removal")
    public static void runtimeIndexMatchesManagerAndCaches(GameTestHelper helper) throws Exception {
        var server = helper.getLevel().getServer();
        var index = RuntimeKnowledge.get(server);
        helper.assertTrue(index.stats().totalRecipes() == server.getRecipeManager().getRecipes().size(), "Index manager count mismatch");
        helper.assertTrue(index.recipesFor("minecraft:diamond_pickaxe").stream().anyMatch(r -> r.id().equals("minecraft:diamond_pickaxe") && r.dependencySupported()), "Live crafting recipe not indexed");
        helper.assertTrue(index.recipesFor("minecraft:glass").stream().anyMatch(r -> r.type().equals("minecraft:smelting") && r.dependencySupported()
                && r.limitations().stream().anyMatch(s -> s.toLowerCase().contains("fuel"))), "Smelting material model/fuel uncertainty missing");
        helper.assertTrue(index.recipesFor("minecraft:structure_void").stream().noneMatch(r -> r.dependencySupported()), "Empty tag incorrectly supported");
        for (int i = 0; i < 20; i++) helper.assertTrue(RuntimeKnowledge.get(server) == index, "Repeated lookup rebuilt index");
        NeoForge.EVENT_BUS.post(new OnDatapackSyncEvent(server.getPlayerList(), helper.makeMockServerPlayerInLevel()));
        helper.assertTrue(RuntimeKnowledge.get(server) == index, "Joining-player sync rebuilt index");
        var rejected = CompletableFuture.supplyAsync(() -> {
            try { RuntimeKnowledge.get(server); return false; }
            catch (IllegalStateException expected) { return true; }
        }).get(5, java.util.concurrent.TimeUnit.SECONDS);
        helper.assertTrue(rejected, "Off-thread index access allowed");
        writeEvidence("m2-index.json", Map.of("generation", index.generation(), "stats", index.stats(), "outputs", index.recipesByOutput().size(), "complete", index.complete(), "pickaxe", index.recipesFor("minecraft:diamond_pickaxe")));
        helper.succeed();
    }
    @GameTest(template = "empty")
    public static void runtimePlannerUsesLiveInventory(GameTestHelper helper) throws Exception {
        var p = player(helper, "m2-plan-fixture");
        // M3 keeps the material assertions and supplies the execution condition M2 left unknown.
        var table = new net.minecraft.core.BlockPos(1, 1, 1);
        helper.setBlock(table, net.minecraft.world.level.block.Blocks.CRAFTING_TABLE);
        var at = helper.absolutePos(table);
        p.setPos(at.getX() + .5, at.getY() + 1, at.getZ() + .5);
        p.getInventory().setItem(0, new ItemStack(Items.DIAMOND, 7));
        p.getInventory().setItem(1, new ItemStack(Items.STICK, 2));
        var service = new PlanningService();
        var ready = service.plan(p, new Goal("minecraft:diamond_pickaxe", 1));
        helper.assertTrue(ready.plan().status().equals("materials_ready"), "Real pickaxe materials should be ready: " + ready.plan().status());
        helper.assertTrue(ready.plan().ownedRequirements().stream().anyMatch(r -> r.item().equals("minecraft:diamond") && r.quantity() == 3), "Live diamonds not allocated exactly once");
        helper.assertTrue(ready.plan().missingRequirements().isEmpty(), "Invented deficit with sufficient ingredients");
        helper.assertTrue(ready.plan().nextAction().kind().equals("prepare_recipe"), "Ready recipe should remain execution-conditional");
        helper.assertTrue(p.getInventory().getItem(0).getCount() == 7 && p.getInventory().getItem(1).getCount() == 2, "Planning consumed real inventory");
        var again = service.plan(p, new Goal("minecraft:diamond_pickaxe", 1));
        helper.assertTrue(ready.plan().selectedPath().equals(again.plan().selectedPath()) && ready.plan().missingRequirements().equals(again.plan().missingRequirements()), "Repeated plan changed deterministic facts");
        p.getInventory().setItem(2, new ItemStack(Items.DIAMOND_PICKAXE));
        helper.assertTrue(service.plan(p, new Goal("minecraft:diamond_pickaxe", 1)).plan().status().equals("already_owned"), "Already-owned goal not recognized");
        try { service.plan(p, new Goal("atm_companion_tests:unregistered", 1)); helper.fail("Nonexistent registry item accepted"); }
        catch (IllegalArgumentException expected) { }
        writeEvidence("m2-live-plan.json", ready);
        helper.succeed();
    }
    @GameTest(template = "empty", timeoutTicks = 200)
    public static void goalsPersistThroughActualSavedDataDiskCodec(GameTestHelper helper) throws Exception {
        var server = helper.getLevel().getServer();
        UUID a = UUID.fromString("07faf504-44b8-4bfa-a795-7e83db0ceea8");
        UUID b = UUID.fromString("4549fb5b-d01a-4d7f-92ab-5934e03568cb");
        var saved = GoalSavedData.get(server);
        saved.set(a, new Goal("minecraft:diamond_pickaxe", 2));
        saved.set(b, new Goal("minecraft:glass", 9));
        helper.assertTrue(GoalSavedData.get(server).goal(a).quantity() == 2, "SavedData not world-persistent in memory");
        Files.createDirectories(Path.of("evidence"));
        Path target = Path.of("evidence/goal-codec-" + UUID.randomUUID() + ".dat");
        saved.save(target.toFile(), server.registryAccess());
        helper.succeedWhen(() -> {
            helper.assertTrue(Files.isRegularFile(target), "Waiting for NeoForge asynchronous SavedData disk write");
            try {
                var nbt = NbtIo.readCompressed(target, NbtAccounter.create(1_048_576));
                var restored = GoalSavedData.load(nbt.getCompound("data"), server.registryAccess());
                helper.assertTrue(restored.goal(a).equals(new Goal("minecraft:diamond_pickaxe", 2)) && restored.goal(b).equals(new Goal("minecraft:glass", 9)), "SavedData disk roundtrip changed private goals");
                restored.clear(a);
                helper.assertTrue(restored.goal(a) == null && restored.goal(b) != null && restored.isDirty(), "Clear corrupted another player's goal");
                CompoundTag malformed = saved.save(new CompoundTag(), server.registryAccess());
                var entries = malformed.getList("goals", 10);
                for (int i = 0; i < entries.size(); i++) {
                    if (entries.getCompound(i).getUUID("player").equals(a)) entries.getCompound(i).putInt("quantity", -1);
                }
                var filtered = GoalSavedData.load(malformed, server.registryAccess());
                helper.assertTrue(filtered.goal(a) == null && filtered.goal(b).equals(new Goal("minecraft:glass", 9)), "Malformed persistent goal accepted or valid goal lost");
            } catch (java.io.IOException exception) { throw new RuntimeException(exception); }
        });
    }
    @GameTest(template = "empty")
    public static void m2CommandsResolveGoalsAndExportBoundedPlans(GameTestHelper helper) throws Exception {
        var server = helper.getLevel().getServer();
        var dispatcher = server.getCommands().getDispatcher();
        var sink = new Output();
        var p = player(helper, "m2-command");
        p.getInventory().setItem(0, new ItemStack(Items.DIAMOND_PICKAXE));
        var source = p.createCommandSourceStack().withPermission(0).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion goal minecraft:diamond_pickaxe", source) == 1, "Goal set command failed");
        helper.assertTrue(GoalSavedData.get(server).goal(p.getUUID()).item().equals("minecraft:diamond_pickaxe"), "Goal not persisted");
        helper.assertTrue(dispatcher.execute("companion goal", source) == 0, "Goal spam not throttled");
        helper.assertTrue(dispatcher.execute("companion goal clear", source) == 1 && GoalSavedData.get(server).goal(p.getUUID()) == null, "Clear command failed");
        helper.assertTrue(sink.messages.size() <= 28 && sink.messages.stream().allMatch(s -> s.length() <= 240), "Goal output unbounded");
        var exporter = player(helper, "m2-export");
        GoalSavedData.get(server).set(exporter.getUUID(), new Goal("minecraft:diamond_pickaxe", 1));
        var exportSource = exporter.createCommandSourceStack().withPermission(2).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion debug plan", exportSource) == 1, "Plan export failed");
        Path export = net.neoforged.fml.loading.FMLPaths.CONFIGDIR.get().resolve("atm_companion/latest-plan.json");
        helper.assertTrue(Files.size(export) <= BoundedJson.MAX_BYTES && com.google.gson.JsonParser.parseString(Files.readString(export)).getAsJsonObject().has("knowledgeGraph"), "Plan export invalid/unbounded");
        var questActor = player(helper, "m2-no-quests").createCommandSourceStack().withPermission(0).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion quests", questActor) == 0, "Absent FTB should be unavailable, not a known empty book");
        var knowledgeActor = player(helper, "m2-knowledge").createCommandSourceStack().withPermission(0).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion knowledge", knowledgeActor) == 1, "Knowledge command failed");
        var nextActor = player(helper, "m2-next");
        GoalSavedData.get(server).set(nextActor.getUUID(), new Goal("minecraft:glass", 1));
        helper.assertTrue(dispatcher.execute("companion next", nextActor.createCommandSourceStack().withPermission(0).withSource(sink)) == 1, "Next command failed");
        var invalid = player(helper, "m2-bad-id").createCommandSourceStack().withPermission(0).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion goal atm_companion_tests:unregistered", invalid) == 0, "Nonexistent goal item accepted");
        helper.succeed();
    }
    @GameTest(template = "empty", batch = "m2_reload", timeoutTicks = 600)
    public static void actualDatapackReloadReplacesRecipeAndTagFacts(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var pending = new AtomicReference<CompletableFuture<Void>>();
        var previous = new AtomicReference<RecipeIndex>();
        Path pack = server.getWorldPath(LevelResource.DATAPACK_DIR).resolve("atm_companion_reload_fixture");
        helper.startSequence().thenExecute(() -> {
            writeReloadPack(pack, "minecraft:oak_planks");
            server.getPackRepository().reload();
            List<String> selected = new ArrayList<>(server.getPackRepository().getSelectedIds());
            if (!selected.contains("file/atm_companion_reload_fixture")) selected.add("file/atm_companion_reload_fixture");
            pending.set(server.reloadResources(selected));
        }).thenWaitUntil(() -> helper.assertTrue(pending.get().isDone()
                && RuntimeKnowledge.status(server).state().equals("ready"), "Waiting for initial real reload and staged index"))
        .thenExecute(() -> {
            pending.get().join();
            RecipeIndex index = RuntimeKnowledge.get(server);
            previous.set(index);
            var recipe = index.recipesById().get("atm_companion_tests:reload_fixture");
            helper.assertTrue(recipe != null && recipe.ingredients().getFirst().alternatives().equals(List.of("minecraft:oak_planks")), "First reloaded recipe/tag absent");
            writeReloadPack(pack, "minecraft:birch_planks");
            pending.set(server.reloadResources(server.getPackRepository().getSelectedIds()));
        }).thenWaitUntil(() -> helper.assertTrue(pending.get().isDone()
                && RuntimeKnowledge.status(server).state().equals("ready"), "Waiting for replacement real reload and staged index"))
        .thenExecute(() -> {
            pending.get().join();
            var current = RuntimeKnowledge.get(server);
            var recipe = current.recipesById().get("atm_companion_tests:reload_fixture");
            helper.assertTrue(current.generation() > previous.get().generation() && current != previous.get(), "Reload reused stale index generation");
            helper.assertTrue(recipe.ingredients().getFirst().alternatives().equals(List.of("minecraft:birch_planks")), "Reload retained stale tag members");
            helper.assertTrue(previous.get().recipesById().get("atm_companion_tests:reload_fixture").ingredients().getFirst().alternatives().equals(List.of("minecraft:oak_planks")), "Published old immutable index mutated");
            var result = new DeterministicPlanner().plan(current, "minecraft:debug_stick", 1, Map.of("minecraft:birch_planks", 1L));
            helper.assertTrue(result.status().equals("materials_ready"), "Planner did not use reloaded requirement");
            try { writeEvidence("m2-reload.json", Map.of("beforeGeneration", previous.get().generation(), "afterGeneration", current.generation(), "newRecipe", recipe, "plan", result)); }
            catch (Exception exception) { throw new RuntimeException(exception); }
        }).thenSucceed();
    }
    private static void writeReloadPack(Path pack, String tagMember) {
        try {
            Path recipe = pack.resolve("data/atm_companion_tests/recipe/reload_fixture.json");
            Path tag = pack.resolve("data/atm_companion_tests/tags/item/reload_material.json");
            Files.createDirectories(recipe.getParent()); Files.createDirectories(tag.getParent());
            Files.writeString(pack.resolve("pack.mcmeta"), "{\"pack\":{\"pack_format\":" + SharedConstants.getCurrentVersion().getPackVersion(PackType.SERVER_DATA) + ",\"description\":\"ATM Companion reload test only\"}}");
            Files.writeString(recipe, "{\"type\":\"minecraft:crafting_shapeless\",\"ingredients\":[{\"tag\":\"atm_companion_tests:reload_material\"}],\"result\":{\"id\":\"minecraft:debug_stick\",\"count\":1}}");
            Files.writeString(tag, "{\"replace\":true,\"values\":[\"" + tagMember + "\"]}");
        } catch (java.io.IOException exception) { throw new RuntimeException(exception); }
    }
    private static void writeEvidence(String name, Object value) throws Exception {
        Files.createDirectories(Path.of("evidence"));
        Files.writeString(Path.of("evidence").resolve(name), BoundedJson.encode(value));
    }
    private static final class Output implements CommandSource {
        final List<String> messages = new ArrayList<>();
        @Override public void sendSystemMessage(Component message) { messages.add(message.getString()); }
        @Override public boolean acceptsSuccess() { return true; }
        @Override public boolean acceptsFailure() { return true; }
        @Override public boolean shouldInformAdmins() { return false; }
    }
}
