package dev.atmcompanion.tests;

import com.mojang.authlib.GameProfile;
import dev.atmcompanion.execution.ExecutionContext;
import dev.atmcompanion.execution.StationService;
import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.knowledge.RecipeIndexBuilder;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import dev.atmcompanion.planning.BoundedJson;
import dev.atmcompanion.planning.Goal;
import dev.atmcompanion.planning.PlanningService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import net.minecraft.core.BlockPos;
import net.minecraft.commands.CommandSource;
import net.minecraft.core.NonNullList;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.crafting.CookingBookCategory;
import net.minecraft.world.item.crafting.CraftingBookCategory;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.RecipeType;
import net.minecraft.world.item.crafting.ShapedRecipe;
import net.minecraft.world.item.crafting.ShapedRecipePattern;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import net.minecraft.world.item.crafting.SingleRecipeInput;
import net.minecraft.world.item.crafting.SmeltingRecipe;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.block.entity.FurnaceBlockEntity;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;

/** Disposable headless fixtures only. Never points at the user's instance or survival world. */
@GameTestHolder("atm_companion_tests")
@PrefixGameTestTemplate(false)
public final class M3GameTests {
    @GameTest(template = "empty", batch = "m3_execution")
    public static void realRecipeShapesAndCookingDurationArePreserved(GameTestHelper helper) {
        var registries = helper.getLevel().registryAccess();
        var key = Map.of('X', Ingredient.of(Items.STICK));
        var column = new ShapedRecipe("", CraftingBookCategory.MISC, ShapedRecipePattern.of(key, "X", " ", "X"), new ItemStack(Items.STONE));
        var row = new ShapedRecipe("", CraftingBookCategory.MISC, ShapedRecipePattern.of(key, "X X"), new ItemStack(Items.STONE));
        var square = new ShapedRecipe("", CraftingBookCategory.MISC, ShapedRecipePattern.of(key, "XX", "XX"), new ItemStack(Items.STONE));
        var c = RecipeIndexBuilder.normalize(new RecipeHolder<>(id("column"), column), registries);
        var r = RecipeIndexBuilder.normalize(new RecipeHolder<>(id("row"), row), registries);
        var s = RecipeIndexBuilder.normalize(new RecipeHolder<>(id("square"), square), registries);
        helper.assertTrue(c.ingredients().size() == 2 && c.execution().width() == 1 && c.execution().height() == 3
                && !c.execution().fits2x2() && c.execution().fits3x3(), "Sparse 1x3 shape incorrectly collapsed to ingredient count");
        helper.assertTrue(r.execution().width() == 3 && r.execution().height() == 1 && !r.execution().fits2x2(), "Sparse 3x1 shape lost");
        helper.assertTrue(s.execution().fits2x2() && s.execution().fits3x3(), "Actual 2x2 recipe requires an invented station");
        for (int count : new int[]{4, 5}) {
            var recipe = new ShapelessRecipe("", CraftingBookCategory.MISC, new ItemStack(Items.STONE),
                    NonNullList.withSize(count, Ingredient.of(Items.STICK)));
            var facts = RecipeIndexBuilder.normalize(new RecipeHolder<>(id("shapeless_" + count), recipe), registries);
            helper.assertTrue(facts.execution().fits2x2() == (count == 4) && facts.execution().fits3x3(), "Shapeless grid fit invented");
        }
        var cooking = new SmeltingRecipe("", CookingBookCategory.MISC, Ingredient.of(Items.COBBLESTONE), new ItemStack(Items.STONE), 0, 321);
        var facts = RecipeIndexBuilder.normalize(new RecipeHolder<>(id("cook_time"), cooking), registries);
        helper.assertTrue(facts.execution().kind().equals("smelting") && facts.execution().cookingTicks() == 321,
                "Cooking duration was hardcoded instead of read from recipe");
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_execution")
    public static void stationFactsReserveFuelAndNeverMutateInventories(GameTestHelper helper) {
        var p = player(helper, "m3-station");
        BlockPos furnacePos = helper.absolutePos(new BlockPos(1, 1, 1));
        helper.getLevel().setBlockAndUpdate(furnacePos, Blocks.FURNACE.defaultBlockState());
        helper.getLevel().setBlockAndUpdate(furnacePos.east(), Blocks.SMOKER.defaultBlockState());
        helper.getLevel().setBlockAndUpdate(furnacePos.west(), Blocks.CRAFTING_TABLE.defaultBlockState());
        p.setPos(furnacePos.getX() + .5, furnacePos.getY(), furnacePos.getZ() + 2.5);
        p.getInventory().setItem(0, new ItemStack(Items.COBBLESTONE, 2));
        p.getInventory().setItem(1, new ItemStack(Items.OAK_PLANKS));
        p.getInventory().setItem(2, new ItemStack(Items.COAL));
        var furnace = (FurnaceBlockEntity) helper.getLevel().getBlockEntity(furnacePos);
        furnace.setItem(2, new ItemStack(Items.DIRT));
        var before = furnace.saveCustomOnly(helper.getLevel().registryAccess());
        List<ItemStack> beforeInventory = new ArrayList<>();
        for (int slot = 0; slot < 36; slot++) beforeInventory.add(p.getInventory().getItem(slot).copy());
        var service = new StationService(() -> 0L);
        var facts = service.capture(p, smeltingStone(helper), Map.of("minecraft:cobblestone", 2L, "minecraft:oak_planks", 1L));
        helper.assertTrue(facts.operation().data() != null && Boolean.TRUE.equals(facts.operation().data().playerInputMatches().data()), "Real player input not matched");
        var station = at(facts, furnacePos);
        helper.assertTrue(station.details().data() != null, "Actual furnace detail inspection unavailable");
        helper.assertTrue(Boolean.TRUE.equals(station.details().data().inputCompatible().data()), "Empty furnace input incorrectly blocked");
        helper.assertTrue(Boolean.FALSE.equals(station.details().data().outputCompatible().data()), "Incompatible dirt output falsely considered usable");
        helper.assertTrue(station.details().data().timers().data() != null, "Pinned vanilla timer serialization not actually supported");
        var planks = facts.fuelSlots().stream().filter(slot -> slot.slot() == 1).findFirst().orElseThrow();
        var coal = facts.fuelSlots().stream().filter(slot -> slot.slot() == 2).findFirst().orElseThrow();
        helper.assertTrue(planks.count() == 1 && planks.availableAfterReservation() == 0, "Reserved ingredient double-counted as fuel");
        helper.assertTrue(coal.availableAfterReservation() == 1 && coal.burnTicksPerItem().data() != null && coal.burnTicksPerItem().data() > 0, "Runtime coal fuel hook unavailable");
        helper.assertTrue(at(facts, furnacePos.east()).details().data() == null, "Wrong station type got recipe-specific details");
        helper.assertTrue(before.equals(furnace.saveCustomOnly(helper.getLevel().registryAccess())), "Observation mutated furnace state");
        for (int slot = 0; slot < 36; slot++) helper.assertTrue(ItemStack.matches(beforeInventory.get(slot), p.getInventory().getItem(slot)), "Observation mutated player inventory");
        furnace.setItem(0, new ItemStack(Items.DIRT));
        furnace.setItem(2, new ItemStack(Items.STONE, Items.STONE.getDefaultMaxStackSize()));
        var blocked = at(service.capture(p, smeltingStone(helper), Map.of()), furnacePos).details().data();
        helper.assertTrue(Boolean.FALSE.equals(blocked.inputCompatible().data()) && Boolean.FALSE.equals(blocked.outputCompatible().data()), "Occupied input/full output not blocked");
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_station_caps")
    public static void deepInspectionBudgetIsSharedAcrossCandidateCaptures(GameTestHelper helper) {
        var p = player(helper, "m3-deep-caps");
        BlockPos center = helper.absolutePos(new BlockPos(2, 1, 2));
        p.setPos(center.getX() + .5, center.getY() + 1, center.getZ() + .5);
        p.getInventory().setItem(0, new ItemStack(Items.COBBLESTONE));
        for (int x = -2; x <= 2; x++) for (int z = -2; z <= 2; z++) {
            helper.getLevel().setBlockAndUpdate(center.offset(x, 0, z), Blocks.FURNACE.defaultBlockState());
        }
        var session = new StationService(() -> 0L).begin(p);
        var first = session.capture(smeltingStone(helper), Map.of());
        var second = session.capture(smeltingStone(helper), Map.of());
        helper.assertTrue(first.scan().deepInspections() == StationService.MAX_DEEP, "Fixture did not reach deep inspection cap");
        helper.assertTrue(second.scan().deepInspections() == StationService.MAX_DEEP, "Repeated candidate got an additional deep inspection budget");
        helper.assertTrue(second.scan().predicateChecks() <= StationService.MAX_PREDICATES && second.stations().size() <= StationService.MAX_STATIONS, "Shared observation bounds escaped");
        helper.assertTrue(second.stations().stream().anyMatch(station -> station.details().data() == null), "Uninspected station silently became known empty");
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_execution")
    public static void unloadedScopesAreUnknownAndDoNotForceChunkLoads(GameTestHelper helper) {
        var p = player(helper, "m3-no-chunks");
        p.setPos(20_000_000.5, 100, 20_000_000.5);
        var source = helper.getLevel().getChunkSource();
        helper.assertTrue(source.getChunkNow(p.blockPosition().getX() >> 4, p.blockPosition().getZ() >> 4) == null, "Fixture's remote chunk unexpectedly loaded");
        int before = source.getLoadedChunksCount();
        var facts = new StationService(() -> 0L).scan(p);
        helper.assertTrue(facts.scan().unloadedPositions() > 0 && !facts.scan().complete(), "Unloaded scope reported as known absence");
        helper.assertTrue(facts.stations().isEmpty() && source.getLoadedChunksCount() == before, "Observation forced chunk loading");
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_execution")
    public static void staleOffThreadAndTimedOutObservationsRemainExplicit(GameTestHelper helper) throws Exception {
        var p = player(helper, "m3-stale");
        var session = new StationService(() -> 0L).begin(p);
        p.getInventory().setItem(0, new ItemStack(Items.STICK));
        boolean rejected = false;
        try { session.scan(); } catch (IllegalStateException expected) { rejected = true; }
        helper.assertTrue(rejected, "Same-tick changed inventory reused a stale observation session");
        boolean offThread = CompletableFuture.supplyAsync(() -> {
            try { new StationService().scan(p); return false; }
            catch (IllegalStateException expected) { return true; }
        }).get(5, TimeUnit.SECONDS);
        helper.assertTrue(offThread, "Off-thread world observation allowed");
        var clock = new AtomicLong();
        var timed = new StationService(() -> clock.getAndAdd(StationService.BUDGET_NANOS)).scan(p);
        helper.assertTrue(timed.scan().budgetExceeded() && timed.scan().scannedPositions() == 0 && !timed.scan().complete(), "Expired scan became a known empty area");
        helper.assertTrue(StationService.readTimers(new CompoundTag(), false).data() == null, "Missing timer tags became zero energy");
        CompoundTag malformed = new CompoundTag();
        malformed.putString("BurnTime", "0"); malformed.putInt("CookTime", 0); malformed.putInt("CookTimeTotal", 200);
        helper.assertTrue(StationService.readTimers(malformed, false).data() == null, "Wrong timer NBT type became known energy");
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_execution")
    public static void deadAndSpectatorPlayersCannotReceiveOperationReadiness(GameTestHelper helper) {
        var p = player(helper, "m3-player-state");
        var recipe = smeltingStone(helper);
        var service = new StationService(() -> 0L);
        p.getInventory().setItem(0, new ItemStack(Items.COBBLESTONE));
        try {
            p.setGameMode(GameType.SPECTATOR);
            helper.assertTrue(p.isSpectator(), "Spectator fixture failed to enter its requested game mode");
            helper.assertTrue(service.capture(p, recipe, Map.of()).operation().data() == null,
                    "A spectator with material items was told it could perform an operation");
            p.setGameMode(GameType.SURVIVAL);
            p.setHealth(0);
            helper.assertTrue(!p.isAlive(), "Dead fixture is still alive");
            helper.assertTrue(service.capture(p, recipe, Map.of()).operation().data() == null,
                    "A dead player was told it could perform an operation");
        } finally {
            p.setHealth(p.getMaxHealth());
            p.setGameMode(GameType.SURVIVAL);
        }
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_execution", timeoutTicks = 300)
    public static void slicedIndexSchedulingDoesNotChangeRecipeFacts(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var definitions = new ArrayList<RecipeHolder<?>>();
        for (int i = 0; i < 600; i++) definitions.add(new RecipeHolder<>(id("sliced_" + i),
                new ShapelessRecipe("", CraftingBookCategory.MISC, new ItemStack(Items.STONE), NonNullList.of(Ingredient.EMPTY, Ingredient.of(Items.STICK)))));
        var slow = RecipeIndexBuilder.start(server, 80_001, definitions);
        boolean earlyRejected = false;
        try { slow.result(); } catch (IllegalStateException expected) { earlyRejected = true; }
        helper.assertTrue(earlyRejected, "Building index was exposed as ready");
        int slices = 0;
        while (!slow.done() && slices++ < 10_000) {
            var before = slow.progress();
            slow.advance(1);
            var after = slow.progress();
            helper.assertTrue(after.visitedDefinitions() - before.visitedDefinitions() <= RecipeIndexBuilder.SELECTION_OPERATIONS_PER_SLICE, "Selection slice unbounded");
            helper.assertTrue(after.normalizedDefinitions() - before.normalizedDefinitions() <= RecipeIndexBuilder.NORMALIZATION_OPERATIONS_PER_SLICE, "Normalization slice unbounded");
            helper.assertTrue(after.lookupDefinitions() - before.lookupDefinitions() <= RecipeIndexBuilder.LOOKUP_OPERATIONS_PER_SLICE, "Lookup slice unbounded");
        }
        helper.assertTrue(slow.done(), "Finite sliced index failed to finish");
        Collections.reverse(definitions);
        var normal = RecipeIndexBuilder.build(server, 80_002, definitions);
        helper.assertTrue(slow.result().schemaVersion() == 2 && slow.result().recipesById().equals(normal.recipesById()), "Clock slicing or source order changed normalized facts");
        helper.assertTrue(slow.result().recipesByOutput().equals(normal.recipesByOutput()) && slow.result().outputRecipeCounts().equals(normal.outputRecipeCounts()), "Slicing changed route lookup facts");
        helper.assertTrue(slow.result().stats().indexedRecipes() == 600 && slow.result().coverage().reasons().equals(normal.coverage().reasons()), "Small time slices silently discarded knowledge");
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_recipe_replacement", timeoutTicks = 300)
    public static void replacementInvalidatesKnowledgeAndUnsupportedLiveOutputsStayUnknown(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var manager = server.getRecipeManager();
        var original = new ArrayList<RecipeHolder<?>>(manager.getRecipes());
        var realStone = smeltingStone(helper);
        int replacementSlot = -1;
        for (int i = 0; i < original.size(); i++) if (original.get(i).id().toString().equals(realStone.id())) replacementSlot = i;
        helper.assertTrue(replacementSlot >= 0, "Real stone recipe missing from fixture source");
        var p = player(helper, "m3-replacement");
        var furnacePos = helper.absolutePos(new BlockPos(1, 1, 1));
        helper.getLevel().setBlockAndUpdate(furnacePos, Blocks.FURNACE.defaultBlockState());
        p.setPos(furnacePos.getX() + .5, furnacePos.getY(), furnacePos.getZ() + 2.5);
        p.getInventory().setItem(0, new ItemStack(Items.COBBLESTONE));
        var oversized = new RecipeHolder<>(ResourceLocation.parse(realStone.id()), new SmeltingRecipe("", CookingBookCategory.MISC,
                Ingredient.of(Items.COBBLESTONE), new ItemStack(Items.STONE, 65), 0, 200));
        var replacement = new ArrayList<>(original);
        replacement.set(replacementSlot, oversized);
        try {
            RuntimeKnowledge.rebuild(server);
            var unchanged = RuntimeKnowledge.get(server);
            helper.assertTrue(RuntimeKnowledge.get(server) == unchanged, "Stable definition table was incorrectly invalidated");
            manager.replaceRecipes(replacement);
            boolean rejected = false;
            try { RuntimeKnowledge.get(server); } catch (IllegalStateException expected) { rejected = true; }
            helper.assertTrue(rejected && RuntimeKnowledge.status(server).state().equals("recovering"),
                    "Same-count, same-ID definition replacement exposed stale knowledge");
            var facts = new StationService(() -> 0L).capture(p, RecipeIndexBuilder.normalize(oversized, helper.getLevel().registryAccess()), Map.of());
            helper.assertTrue(Boolean.FALSE.equals(at(facts, furnacePos).details().data().outputCompatible().data()),
                    "Oversized actual recipe output was accepted into an empty furnace output slot");

            boolean bundleEnabled = new ItemStack(Items.BUNDLE).isItemEnabled(helper.getLevel().enabledFeatures());
            var disabled = new RecipeHolder<>(ResourceLocation.parse(realStone.id()), new ShapelessRecipe("", CraftingBookCategory.MISC,
                    new ItemStack(Items.BUNDLE), NonNullList.of(Ingredient.EMPTY, Ingredient.of(Items.COBBLESTONE))));
            replacement.set(replacementSlot, disabled);
            manager.replaceRecipes(replacement);
            var feature = new StationService(() -> 0L).capture(p, RecipeIndexBuilder.normalize(disabled, helper.getLevel().registryAccess()), Map.of());
            if (bundleEnabled) helper.assertTrue(feature.operation().data() != null,
                    "An enabled crafting output was incorrectly suppressed by the feature guard");
            else helper.assertTrue(feature.operation().data() == null && feature.operation().detail().contains("feature"),
                    "A crafting output disabled by world feature flags was presented as usable");

            manager.replaceRecipes(original);
            long cancelled = RuntimeKnowledge.schedule(server);
            long newest = RuntimeKnowledge.schedule(server);
            helper.assertTrue(newest == cancelled + 1 && RuntimeKnowledge.status(server).state().equals("building"), "Replacement job did not cancel old generation");
            rejected = false;
            try { RuntimeKnowledge.get(server); } catch (IllegalStateException expected) { rejected = true; }
            helper.assertTrue(rejected, "Previous or partial generation exposed while replacement was building");
            for (int i = 0; i < 10_000 && RuntimeKnowledge.status(server).state().equals("building"); i++) RuntimeKnowledge.advance(server);
            helper.assertTrue(RuntimeKnowledge.get(server).generation() == newest, "Cancelled generation was published instead of the new generation");

            RuntimeKnowledge.schedule(server);
            manager.replaceRecipes(replacement);
            RuntimeKnowledge.advance(server);
            helper.assertTrue(RuntimeKnowledge.status(server).state().equals("recovering"), "Pending index ignored same-count table replacement");
        } finally {
            manager.replaceRecipes(original);
            RuntimeKnowledge.rebuild(server);
        }
        helper.succeed();
    }

    @GameTest(template = "empty", batch = "m3_execution", timeoutTicks = 400)
    public static void planningServiceCombinesRealMaterialsFuelAndBoundedStationCommands(GameTestHelper helper) {
        // The real production index is staged across ticks. Wait for publication instead of
        // depending on which test batch happens to start after the last startup slice.
        helper.startSequence().thenWaitUntil(() -> {
            var status = RuntimeKnowledge.status(helper.getLevel().getServer());
            helper.assertTrue(status.state().equals("ready"),
                    "Waiting for the production recipe index: " + status.state() + ": " + status.detail());
        }).thenExecute(() -> {
            try { assertPlanningServiceCombinesRealMaterialsFuelAndBoundedStationCommands(helper); }
            catch (Exception exception) { throw new RuntimeException(exception); }
        }).thenSucceed();
    }

    private static void assertPlanningServiceCombinesRealMaterialsFuelAndBoundedStationCommands(GameTestHelper helper) throws Exception {
        var p = player(helper, "m3-plan-service");
        var pos = helper.absolutePos(new BlockPos(1, 1, 1));
        helper.getLevel().setBlockAndUpdate(pos, Blocks.FURNACE.defaultBlockState());
        p.setPos(pos.getX() + .5, pos.getY(), pos.getZ() + 2.5);
        p.getInventory().setItem(0, new ItemStack(Items.COBBLESTONE));
        p.getInventory().setItem(1, new ItemStack(Items.COAL));
        var furnace = (FurnaceBlockEntity) helper.getLevel().getBlockEntity(pos);
        var before = furnace.saveCustomOnly(helper.getLevel().registryAccess());
        var report = new PlanningService(new StationService(() -> 0L)).plan(p, new Goal("minecraft:stone", 1));
        helper.assertTrue(report.plan().status().equals("materials_ready"), "End-to-end real material path missing");
        var execution = report.plan().execution();
        helper.assertTrue(execution.status().equals("observed_conditions_met") && execution.operations() == 1,
                "Real input, station and fuel were not combined into one observed operation: " + execution.status() + " " + execution.blockers());
        helper.assertTrue(execution.inputs().size() == 1 && execution.inputs().getFirst().item().equals("minecraft:cobblestone")
                && execution.inputs().getFirst().quantity() == 1, "Selected real ingredient provenance lost");
        helper.assertTrue(execution.fuel().stream().anyMatch(f -> f.source().equals("player") && f.item().equals("minecraft:coal") && f.count() == 1),
                "Real unreserved coal was not recognized through runtime fuel hook");
        helper.assertTrue(report.questContext().data() == null && report.questContext().detail().contains("not requested"),
                "Default planning performed or claimed a quest observation");
        helper.assertTrue(report.timings().totalNanos() >= report.timings().materialNanos() + report.timings().executionNanos() + report.timings().questNanos(),
                "Stage timings exceed measured end-to-end work");
        helper.assertTrue(p.getInventory().getItem(0).getCount() == 1 && p.getInventory().getItem(1).getCount() == 1
                && before.equals(furnace.saveCustomOnly(helper.getLevel().registryAccess())), "Planning mutated items or furnace state");

        var sink = new Output();
        var dispatcher = helper.getLevel().getServer().getCommands().getDispatcher();
        helper.assertTrue(dispatcher.execute("companion stations", p.createCommandSourceStack().withPermission(0).withSource(sink)) == 1,
                "Non-operator station query failed");
        helper.assertTrue(sink.messages.size() <= 8 && sink.messages.stream().allMatch(s -> s.length() <= 240), "Station command chat escaped its page bounds");
        helper.assertTrue(sink.messages.stream().anyMatch(s -> s.contains("ownership unverified")), "Station command implied nearby inventory ownership");
        var other = player(helper, "m3-station-page");
        helper.assertTrue(dispatcher.execute("companion stations 2147483647", other.createCommandSourceStack().withPermission(0).withSource(sink)) == 0,
                "Oversized station page was accepted");
        Files.createDirectories(Path.of("evidence"));
        Files.writeString(Path.of("evidence/m3-cooking-plan.json"), BoundedJson.encode(report));
    }

    private static NormalizedRecipe smeltingStone(GameTestHelper helper) {
        var level = helper.getLevel();
        var recipe = level.getRecipeManager().getAllRecipesFor(RecipeType.SMELTING).stream()
                .filter(holder -> holder.value().getClass() == SmeltingRecipe.class
                        && holder.value().matches(new SingleRecipeInput(new ItemStack(Items.COBBLESTONE)), level)
                        && holder.value().getResultItem(level.registryAccess()).is(Items.STONE)).findFirst().orElseThrow();
        return RecipeIndexBuilder.normalize(recipe, level.registryAccess());
    }
    private static ExecutionContext.Station at(ExecutionContext context, BlockPos pos) {
        return context.stations().stream().filter(station -> station.x() == pos.getX() && station.y() == pos.getY() && station.z() == pos.getZ()).findFirst().orElseThrow();
    }
    private static ServerPlayer player(GameTestHelper helper, String name) {
        var p = FakePlayerFactory.get(helper.getLevel(), new GameProfile(UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)), name));
        p.getInventory().clearContent();
        BlockPos pos = helper.absolutePos(BlockPos.ZERO);
        p.setPos(pos.getX() + .5, pos.getY() + 1, pos.getZ() + .5);
        return p;
    }
    private static ResourceLocation id(String path) { return ResourceLocation.fromNamespaceAndPath("atm_companion_tests", path); }
    private static final class Output implements CommandSource {
        final List<String> messages = new ArrayList<>();
        @Override public void sendSystemMessage(Component message) { messages.add(message.getString()); }
        @Override public boolean acceptsSuccess() { return true; }
        @Override public boolean acceptsFailure() { return true; }
        @Override public boolean shouldInformAdmins() { return false; }
    }
}
