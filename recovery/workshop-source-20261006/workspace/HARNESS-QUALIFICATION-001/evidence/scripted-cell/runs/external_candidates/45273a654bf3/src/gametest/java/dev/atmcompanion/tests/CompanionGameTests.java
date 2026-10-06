package dev.atmcompanion.tests;

import com.mojang.authlib.GameProfile;
import dev.atmcompanion.state.CapabilityStatus;
import dev.atmcompanion.state.GameSnapshot;
import dev.atmcompanion.state.SnapshotJson;
import dev.atmcompanion.state.SnapshotService;
import dev.atmcompanion.knowledge.RecipeService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.commands.CommandSource;
import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.GameType;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;

/** Uses actual game registries, recipes, advancement manager, and logical-server APIs. */
@GameTestHolder("atm_companion_tests")
@PrefixGameTestTemplate(false)
public final class CompanionGameTests {
    private static ServerPlayer player(GameTestHelper helper, String name) {
        var player = FakePlayerFactory.get(helper.getLevel(), new GameProfile(UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)), name));
        player.getInventory().clearContent();
        player.setGameMode(GameType.SURVIVAL);
        return player;
    }

    @GameTest(template = "empty")
    public static void liveSnapshotMatchesServerState(GameTestHelper helper) throws Exception {
        var player = player(helper, "snapshot-fixture");
        player.setHealth(13);
        player.getFoodData().setFoodLevel(17);
        player.getFoodData().setSaturation(3.5F);
        player.experienceLevel = 9;
        player.setPos(103.25, 70, -44.5);
        player.getInventory().setItem(0, new ItemStack(Items.DIAMOND, 7));
        player.getInventory().selected = 0;
        player.setItemSlot(EquipmentSlot.HEAD, new ItemStack(Items.IRON_HELMET));
        var snapshot = new SnapshotService().capture(player);
        helper.assertTrue(snapshot.player().status() == CapabilityStatus.AVAILABLE, "Player API unavailable");
        helper.assertTrue(snapshot.player().data().health() == 13 && snapshot.player().data().food() == 17
                && snapshot.player().data().experienceLevel() == 9 && snapshot.player().data().saturation() == 3.5F, "Player values do not match live fixture");
        helper.assertTrue(snapshot.location().data().x() == 103.25 && snapshot.location().data().z() == -44.5, "Position mismatch");
        helper.assertTrue(snapshot.location().data().dimension().equals(player.serverLevel().dimension().location().toString()), "Dimension mismatch");
        helper.assertTrue(snapshot.location().data().biome().equals(player.serverLevel().getBiome(player.blockPosition()).unwrapKey().orElseThrow().location().toString()), "Biome mismatch");
        helper.assertTrue(snapshot.inventory().data().stacks().stream().anyMatch(i -> i.item().equals("minecraft:diamond") && i.count() == 7 && i.slot() == 0), "Inventory registry/count/slot mismatch");
        helper.assertTrue(snapshot.equipment().data().head().item().equals("minecraft:iron_helmet"), "Equipment mismatch");
        helper.assertTrue(snapshot.modpack().data().mods().stream().anyMatch(m -> m.id().equals("atm_companion")), "NeoForge did not load production mod metadata");
        helper.assertTrue(snapshot.capabilities().get("quests").status() == CapabilityStatus.NOT_INTEGRATED, "Missing integration presented as known");
        helper.assertTrue(snapshot.progression().status() == CapabilityStatus.UNAVAILABLE, "Synthetic player's dummy progression presented as known");
        String json = SnapshotJson.toJson(snapshot);
        helper.assertTrue(snapshot.equals(SnapshotJson.fromJson(json)), "Live snapshot JSON did not roundtrip");
        Files.createDirectories(Path.of("evidence"));
        Files.writeString(Path.of("evidence/live-snapshot.json"), json);
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void emptyInventoryIsKnownEmpty(GameTestHelper helper) {
        var snapshot = new SnapshotService().capture(player(helper, "empty-fixture"));
        helper.assertTrue(snapshot.inventory().status() == CapabilityStatus.AVAILABLE && snapshot.inventory().data().stacks().isEmpty(), "Empty inventory was unknown or nonempty");
        helper.assertTrue(snapshot.equipment().data().mainHand() == null && snapshot.equipment().data().offHand() == null, "Empty hands mismatch");
        helper.succeed();
    }

    @GameTest(template = "empty")
    @SuppressWarnings("removal") // Official 1.21.1 helper creates a real ServerPlayer with an embedded connection.
    public static void advancementCompletionComesFromServer(GameTestHelper helper) {
        var player = helper.makeMockServerPlayerInLevel();
        helper.assertTrue(!player.isFakePlayer(), "Positive progression test requires real PlayerAdvancements");
        var advancement = player.getServer().getAdvancements().get(ResourceLocation.parse("minecraft:story/root"));
        helper.assertTrue(advancement != null, "Vanilla advancement missing from real manager");
        for (String criterion : advancement.value().criteria().keySet()) player.getAdvancements().revoke(advancement, criterion);
        var before = new SnapshotService().capture(player).progression();
        helper.assertTrue(before.status() == CapabilityStatus.AVAILABLE, "Advancement sensor unavailable");
        for (String criterion : advancement.value().criteria().keySet()) player.getAdvancements().award(advancement, criterion);
        var after = new SnapshotService().capture(player).progression();
        helper.assertTrue(after.data().completed() > before.data().completed(), "Awarded criterion not reflected in completion count");
        helper.assertTrue(after.data().scanned() == player.getServer().getAdvancements().getAllAdvancements().size(), "Advancement scan count mismatch");
        try {
            Files.createDirectories(Path.of("evidence"));
            Files.writeString(Path.of("evidence/real-server-player-snapshot.json"), SnapshotJson.toJson(new SnapshotService().capture(player)));
        } catch (java.io.IOException exception) { throw new RuntimeException(exception); }
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void offThreadCaptureIsRejected(GameTestHelper helper) throws Exception {
        var player = player(helper, "thread-fixture");
        var result = java.util.concurrent.CompletableFuture.supplyAsync(() -> {
            try { new SnapshotService().capture(player); return false; }
            catch (IllegalStateException expected) { return true; }
        }).get(5, java.util.concurrent.TimeUnit.SECONDS);
        helper.assertTrue(result, "Unsafe off-thread live capture was accepted");
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void realRecipesDistinguishShortageAndSufficiency(GameTestHelper helper) {
        var player = player(helper, "recipe-fixture");
        player.getInventory().setItem(0, new ItemStack(Items.DIAMOND, 7));
        var service = new RecipeService();
        var missing = service.find(player, ResourceLocation.parse("minecraft:diamond_pickaxe"));
        var recipe = missing.recipes().stream().filter(r -> r.recipeId().equals("minecraft:diamond_pickaxe")).findFirst().orElseThrow();
        helper.assertTrue(recipe.ingredients().size() == 5, "Runtime pickaxe ingredients incorrect");
        helper.assertTrue(recipe.inventorySatisfiesIngredients().status() == CapabilityStatus.AVAILABLE && !recipe.inventorySatisfiesIngredients().data(), "Missing sticks claimed satisfied");
        player.getInventory().setItem(1, new ItemStack(Items.STICK, 2));
        var enough = service.find(player, ResourceLocation.parse("minecraft:diamond_pickaxe")).recipes().stream()
                .filter(r -> r.recipeId().equals("minecraft:diamond_pickaxe")).findFirst().orElseThrow();
        helper.assertTrue(enough.inventorySatisfiesIngredients().data(), "Two sticks and seven diamonds should satisfy one craft's ingredient multiset");
        var furnace = service.find(player, ResourceLocation.parse("minecraft:glass")).recipes();
        helper.assertTrue(furnace.stream().anyMatch(r -> r.recipeType().equals("minecraft:smelting") && r.inventorySatisfiesIngredients().status() == CapabilityStatus.UNAVAILABLE), "Furnace conditions incorrectly treated as known");
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void tagAlternativesRemainAlternatives(GameTestHelper helper) {
        var player = player(helper, "tag-fixture");
        player.getInventory().setItem(0, new ItemStack(Items.OAK_PLANKS));
        player.getInventory().setItem(1, new ItemStack(Items.BIRCH_PLANKS));
        var report = new RecipeService().find(player, ResourceLocation.parse("minecraft:stick"));
        var recipe = report.recipes().stream().filter(r -> r.recipeId().equals("minecraft:stick")).findFirst().orElseThrow();
        helper.assertTrue(recipe.ingredients().stream().allMatch(i -> i.alternatives().contains("minecraft:oak_planks") && i.alternatives().contains("minecraft:birch_planks")), "Plank tag flattened into one item");
        helper.assertTrue(recipe.inventorySatisfiesIngredients().data(), "Different valid planks cannot satisfy tag positions");
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void emptyTagsNeverInventBarrierRequirements(GameTestHelper helper) {
        var player = player(helper, "empty-tag-fixture");
        player.getInventory().setItem(0, new ItemStack(Items.BARRIER, 64));
        var empty = new RecipeService().find(player, ResourceLocation.parse("minecraft:structure_void"));
        var recipe = empty.recipes().stream().filter(r -> r.recipeId().equals("atm_companion_tests:empty_tag")).findFirst().orElseThrow();
        helper.assertTrue(recipe.ingredients().stream().noneMatch(i -> i.alternatives().contains("minecraft:barrier")), "Empty tag leaked NeoForge's visual barrier placeholder into a factual ingredient");
        helper.assertTrue(recipe.inventorySatisfiesIngredients().status() == CapabilityStatus.UNAVAILABLE || !recipe.inventorySatisfiesIngredients().data(), "Barrier placeholder claimed satisfiable");
        var mixed = new RecipeService().find(player, ResourceLocation.parse("minecraft:command_block"));
        var mixedRecipe = mixed.recipes().stream().filter(r -> r.recipeId().equals("atm_companion_tests:mixed_empty_tag")).findFirst().orElseThrow();
        helper.assertTrue(mixedRecipe.ingredients().stream().noneMatch(i -> i.alternatives().contains("minecraft:barrier")), "Mixed empty tag leaked placeholder");
        helper.assertTrue(mixedRecipe.inventorySatisfiesIngredients().status() == CapabilityStatus.UNAVAILABLE || !mixedRecipe.inventorySatisfiesIngredients().data(), "Mixed empty tag falsely matches barrier");
        helper.succeed();
    }

    @GameTest(template = "empty")
    public static void registeredCommandsAreBoundedAndPrivate(GameTestHelper helper) throws Exception {
        var server = helper.getLevel().getServer();
        var dispatcher = server.getCommands().getDispatcher();
        var sink = new Output();
        helper.assertTrue(dispatcher.execute("companion", server.createCommandSourceStack().withSource(sink)) == 1, "Help unavailable from console");
        try {
            dispatcher.execute("companion state", server.createCommandSourceStack().withSource(sink));
            helper.fail("Console state unexpectedly succeeded without a player");
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException expected) { /* Required player constraint */ }
        var actor = player(helper, "command-fixture");
        var source = actor.createCommandSourceStack().withPermission(0).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion state", source) == 1, "Player state command failed");
        helper.assertTrue(dispatcher.execute("companion state", source) == 0, "Snapshot spam was not throttled");
        try {
            dispatcher.execute("companion debug snapshot", source);
            helper.fail("Non-operator could write a server-local export");
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException expected) { /* Permission requirement */ }
        sink.messages.clear();
        helper.assertTrue(dispatcher.execute("companion mods", player(helper, "mods-fixture").createCommandSourceStack().withPermission(0).withSource(sink)) == 1, "Mods command failed");
        helper.assertTrue(sink.messages.size() <= 14 && sink.messages.stream().allMatch(m -> m.length() <= 240), "Mods chat unbounded");
        sink.messages.clear();
        helper.assertTrue(dispatcher.execute("companion capabilities", player(helper, "caps-fixture").createCommandSourceStack().withPermission(0).withSource(sink)) == 1, "Capabilities command failed");
        helper.assertTrue(sink.messages.size() <= 33 && sink.messages.stream().anyMatch(m -> m.contains("not_integrated")), "Capabilities command hides unavailable integrations or is unbounded");
        var exporter = player(helper, "export-fixture").createCommandSourceStack().withPermission(2).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion debug snapshot", exporter) == 1, "Operator export command failed");
        Path exported = net.neoforged.fml.loading.FMLPaths.CONFIGDIR.get().resolve("atm_companion/latest-snapshot.json");
        helper.assertTrue(Files.exists(exported) && Files.size(exported) <= SnapshotJson.MAX_JSON_BYTES, "Export missing or oversized");
        helper.assertTrue(SnapshotJson.fromJson(Files.readString(exported)).schemaVersion() == 1, "Export invalid JSON/schema");
        var query = player(helper, "query-fixture").createCommandSourceStack().withPermission(0).withSource(sink);
        helper.assertTrue(dispatcher.execute("companion recipe minecraft:diamond_pickaxe", query) == 1, "Recipe command failed");
        helper.assertTrue(dispatcher.execute("companion recipe minecraft:diamond_pickaxe", query) == 0, "Recipe spam was not throttled");
        helper.succeed();
    }

    private static final class Output implements CommandSource {
        private final java.util.List<String> messages = new java.util.ArrayList<>();
        @Override public void sendSystemMessage(Component component) { messages.add(component.getString()); }
        @Override public boolean acceptsSuccess() { return true; }
        @Override public boolean acceptsFailure() { return true; }
        @Override public boolean shouldInformAdmins() { return false; }
    }
}
