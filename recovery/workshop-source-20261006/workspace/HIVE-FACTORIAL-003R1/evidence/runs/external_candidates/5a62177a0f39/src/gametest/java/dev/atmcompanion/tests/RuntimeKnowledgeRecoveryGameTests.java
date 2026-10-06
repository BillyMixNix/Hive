package dev.atmcompanion.tests;

import com.mojang.authlib.GameProfile;
import dev.atmcompanion.knowledge.RecipeIndex;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import net.minecraft.core.NonNullList;
import net.minecraft.commands.CommandSource;
import net.minecraft.network.chat.Component;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.gametest.framework.GameTestInfo;
import net.minecraft.gametest.framework.GameTestListener;
import net.minecraft.gametest.framework.GameTestRunner;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.crafting.CraftingBookCategory;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.event.OnDatapackSyncEvent;
import net.neoforged.bus.api.EventPriority;

/** Real late recipe-table replacements, native server ticks, no reload and no user world. */
@GameTestHolder("atm_companion_tests")
@PrefixGameTestTemplate(false)
public final class RuntimeKnowledgeRecoveryGameTests {
    @GameTest(template = "empty", batch = "m3_hotfix_late_tables", timeoutTicks = 600)
    public static void lateJoinAndReloadTableChangesRecoverWithoutStalePublication(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var manager = server.getRecipeManager();
        var original = new ArrayList<RecipeHolder<?>>(manager.getRecipes());
        restoreOnFinish(helper, () -> { manager.replaceRecipes(original); RuntimeKnowledge.rebuild(server); });
        var replacedId = original.getFirst().id();
        RuntimeKnowledge.schedule(server);
        RuntimeKnowledge.advance(server);
        helper.assertTrue(RuntimeKnowledge.status(server).state().equals("building"), "Fixture did not interrupt a partial startup job");
        postLateReplacement(helper, helper.makeMockServerPlayerInLevel(), changed(original, replacedId, Items.DIRT, false));
        rejectStale(helper, server);
        helper.assertTrue(RuntimeKnowledge.status(server).state().equals("recovering"), "Late same-count startup change did not enter bounded recovery");
        assertStateCommand(helper, false);

        int[] stage = {0}, changes = {0}, quietSince = {server.getTickCount()};
        RecipeIndex[] previous = {null};
        long[] waitingGeneration = {RuntimeKnowledge.status(server).generation()};
        helper.onEachTick(() -> {
            var status = RuntimeKnowledge.status(server);
            helper.assertTrue(!status.state().equals("failed"), "Recoverable source change became a permanent index failure: " + status.detail());
            if (stage[0] == 2 && changes[0] < 10) {
                Item member = changes[0] % 2 == 0 ? Items.GOLD_INGOT : Items.IRON_INGOT;
                manager.replaceRecipes(changed(original, replacedId, member, true));
                rejectStale(helper, server);
                quietSince[0] = server.getTickCount();
                changes[0]++;
                var observed = RuntimeKnowledge.status(server);
                helper.assertTrue(observed.state().equals("recovering"), "Noisy source changes started normalization before stabilization");
                if (changes[0] == 1) waitingGeneration[0] = observed.generation();
                helper.assertTrue(observed.generation() == waitingGeneration[0], "Debounce churn allocated a new generation every tick");
                for (int repeat = 0; repeat < 25; repeat++) rejectStale(helper, server);
                helper.assertTrue(RuntimeKnowledge.status(server).generation() == waitingGeneration[0], "Repeated same-tick queries spent recovery generations");
                return;
            }
            if (!status.state().equals("ready")) {
                rejectStale(helper, server);
                if (server.getTickCount() - quietSince[0] < RuntimeKnowledge.STABILIZATION_TICKS)
                    helper.assertTrue(status.state().equals("recovering"), "Recovery skipped required stable server ticks");
                return;
            }
            var index = RuntimeKnowledge.get(server);
            helper.assertTrue(server.getTickCount() - quietSince[0] >= RuntimeKnowledge.STABILIZATION_TICKS, "A new table was published before stabilization");
            if (stage[0] == 0) {
                assertMember(helper, index, replacedId, "minecraft:dirt");
                helper.assertTrue(index.stats().totalRecipes() == original.size(), "Same-count source recovery changed definition count");
                previous[0] = index;
                manager.replaceRecipes(changed(original, replacedId, Items.SAND, true));
                rejectStale(helper, server);
                quietSince[0] = server.getTickCount();
                stage[0] = 1;
            } else if (stage[0] == 1) {
                assertMember(helper, index, replacedId, "minecraft:sand");
                assertMember(helper, previous[0], replacedId, "minecraft:dirt");
                helper.assertTrue(index.generation() > previous[0].generation() && index.stats().totalRecipes() == original.size() + 1,
                        "Ready-state new-count mutation did not publish a new generation");
                stage[0] = 2;
            } else if (stage[0] == 2) {
                helper.assertTrue(changes[0] == 10, "Noise fixture did not execute all source replacements");
                assertMember(helper, index, replacedId, "minecraft:iron_ingot");
                helper.assertTrue(index.stats().totalRecipes() == original.size() + 1, "Final stable table count incorrect");
                // Global reload captures at normal priority; the simulated mod replaces again at LOWEST.
                postLateReplacement(helper, null, changed(original, replacedId, Items.LAPIS_LAZULI, true));
                rejectStale(helper, server);
                quietSince[0] = server.getTickCount();
                stage[0] = 3;
            } else {
                assertMember(helper, index, replacedId, "minecraft:lapis_lazuli");
                helper.succeed();
            }
        });
    }

    @GameTest(template = "empty", batch = "m3_hotfix_churn_cap", timeoutTicks = 600)
    public static void interruptedAutomaticBuildsStopAtTheRestartCapAndStayStopped(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var manager = server.getRecipeManager();
        var original = new ArrayList<RecipeHolder<?>>(manager.getRecipes());
        restoreOnFinish(helper, () -> { manager.replaceRecipes(original); RuntimeKnowledge.rebuild(server); });
        var replacedId = original.getFirst().id();
        RuntimeKnowledge.schedule(server);
        RuntimeKnowledge.advance(server);
        manager.replaceRecipes(changed(original, replacedId, Items.DIRT, false));
        rejectStale(helper, server);
        int[] starts = {0}, failedAt = {-1};
        long[] failedGeneration = {-1};
        helper.onEachTick(() -> {
            var status = RuntimeKnowledge.status(server);
            rejectStale(helper, server);
            if (failedAt[0] >= 0) {
                helper.assertTrue(status.state().equals("failed") && status.generation() == failedGeneration[0],
                        "Terminal failure silently entered an unbounded automatic retry loop");
                if (server.getTickCount() - failedAt[0] >= RuntimeKnowledge.STABILIZATION_TICKS * 2 + 5) helper.succeed();
            } else if (status.state().equals("building")) {
                starts[0]++;
                helper.assertTrue(starts[0] <= RuntimeKnowledge.MAX_AUTOMATIC_RESTARTS, "Automatic starts escaped their cap");
                manager.replaceRecipes(changed(original, replacedId, starts[0] % 2 == 0 ? Items.DIRT : Items.SAND, false));
                rejectStale(helper, server);
            } else if (status.state().equals("failed")) {
                helper.assertTrue(starts[0] == RuntimeKnowledge.MAX_AUTOMATIC_RESTARTS, "Failure happened before or after the documented automatic-start cap");
                failedAt[0] = server.getTickCount();
                failedGeneration[0] = status.generation();
                assertStateCommand(helper, true);
            } else helper.assertTrue(status.state().equals("recovering"), "Unstable job exposed a ready or unsupported lifecycle state");
        });
    }

    @GameTest(template = "empty", batch = "m3_hotfix_continuous_wait", timeoutTicks = 1500)
    public static void continuouslyChangingTableStopsWaitingAtItsActualTickBound(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        var manager = server.getRecipeManager();
        var original = new ArrayList<RecipeHolder<?>>(manager.getRecipes());
        restoreOnFinish(helper, () -> { manager.replaceRecipes(original); RuntimeKnowledge.rebuild(server); });
        var replacedId = original.getFirst().id();
        RuntimeKnowledge.schedule(server);
        RuntimeKnowledge.advance(server);
        manager.replaceRecipes(changed(original, replacedId, Items.DIRT, false));
        rejectStale(helper, server);
        long generation = RuntimeKnowledge.status(server).generation();
        int began = server.getTickCount();
        helper.onEachTick(() -> {
            var status = RuntimeKnowledge.status(server);
            int elapsed = server.getTickCount() - began;
            rejectStale(helper, server);
            helper.assertTrue(status.generation() == generation, "Continuous table noise spent automatic build generations");
            if (status.state().equals("failed")) {
                helper.assertTrue(elapsed >= RuntimeKnowledge.MAX_STABILIZATION_WAIT_TICKS
                        && elapsed <= RuntimeKnowledge.MAX_STABILIZATION_WAIT_TICKS + 3, "Continuous stabilization waiting was not bounded in actual server ticks");
                helper.succeed();
                return;
            }
            helper.assertTrue(status.state().equals("recovering"), "Continuously changing table was treated as stable");
            helper.assertTrue(elapsed <= RuntimeKnowledge.MAX_STABILIZATION_WAIT_TICKS + 2, "Recovery waited forever without publication");
            manager.replaceRecipes(changed(original, replacedId, elapsed % 2 == 0 ? Items.DIRT : Items.SAND, false));
            rejectStale(helper, server);
        });
    }

    private static List<RecipeHolder<?>> changed(List<RecipeHolder<?>> original, ResourceLocation replacedId, Item member, boolean extra) {
        var replacement = new ArrayList<>(original);
        replacement.set(0, new RecipeHolder<>(replacedId, new ShapelessRecipe("", CraftingBookCategory.MISC,
                new ItemStack(Items.STONE), NonNullList.of(Ingredient.EMPTY, Ingredient.of(member)))));
        if (extra) replacement.add(new RecipeHolder<>(ResourceLocation.fromNamespaceAndPath("atm_companion_tests", "late_table_extra"),
                new ShapelessRecipe("", CraftingBookCategory.MISC, new ItemStack(Items.COBBLESTONE), NonNullList.of(Ingredient.EMPTY, Ingredient.of(Items.GRANITE)))));
        return replacement;
    }
    private static void assertMember(GameTestHelper helper, RecipeIndex index, ResourceLocation id, String expected) {
        var recipe = index.recipesById().get(id.toString());
        helper.assertTrue(recipe != null && recipe.dependencySupported() && recipe.ingredients().getFirst().alternatives().equals(List.of(expected)),
                "Published recipe does not match the final real table: " + expected);
    }
    private static void rejectStale(GameTestHelper helper, MinecraftServer server) {
        boolean rejected = false;
        try { RuntimeKnowledge.get(server); } catch (IllegalStateException expected) { rejected = true; }
        helper.assertTrue(rejected, "Stale or partial knowledge was served while recovery was required");
    }
    private static void postLateReplacement(GameTestHelper helper, ServerPlayer player, List<RecipeHolder<?>> recipes) {
        var server = helper.getLevel().getServer();
        Consumer<OnDatapackSyncEvent> late = event -> {
            if (event.getPlayerList() == server.getPlayerList() && event.getPlayer() == player) server.getRecipeManager().replaceRecipes(recipes);
        };
        NeoForge.EVENT_BUS.addListener(EventPriority.LOWEST, late);
        try { NeoForge.EVENT_BUS.post(new OnDatapackSyncEvent(server.getPlayerList(), player)); }
        finally { NeoForge.EVENT_BUS.unregister(late); }
    }
    private static void assertStateCommand(GameTestHelper helper, boolean terminal) {
        String name = terminal ? "failed-chat" : "recovery-chat";
        var player = FakePlayerFactory.get(helper.getLevel(), new GameProfile(UUID.nameUUIDFromBytes(name.getBytes(StandardCharsets.UTF_8)), name));
        var output = new Output();
        try {
            int result = helper.getLevel().getServer().getCommands().getDispatcher().execute("companion recipe minecraft:stone",
                    player.createCommandSourceStack().withPermission(0).withSource(output));
            helper.assertTrue(result == 0, "Recipe query claimed success while its index was unavailable");
        } catch (com.mojang.brigadier.exceptions.CommandSyntaxException failure) { throw new IllegalStateException(failure); }
        helper.assertTrue(output.messages.size() == 2 && output.messages.stream().allMatch(line -> line.length() <= 240), "Expected index-state chat was absent or unbounded");
        helper.assertTrue(output.messages.getFirst().contains(terminal ? "failed" : "recovering"), "Command hid actual lifecycle state");
        String combined = String.join(" ", output.messages);
        helper.assertTrue(!combined.contains("IllegalStateException") && !combined.contains("IndexUnavailableException"), "Expected lifecycle condition became a generic exception message");
        if (terminal) helper.assertTrue(combined.contains("/reload") && !combined.contains("Keep the world running"), "Terminal failure promised an automatic recovery that cannot happen");
        else helper.assertTrue(combined.contains("Keep the world running") && combined.contains("retry"), "Recovering state omitted useful wait/retry guidance");
    }
    private static final class Output implements CommandSource {
        final List<String> messages = new ArrayList<>();
        @Override public void sendSystemMessage(Component message) { messages.add(message.getString()); }
        @Override public boolean acceptsSuccess() { return true; }
        @Override public boolean acceptsFailure() { return true; }
        @Override public boolean shouldInformAdmins() { return false; }
    }
    private static void restoreOnFinish(GameTestHelper helper, Runnable restore) {
        var restored = new AtomicBoolean();
        helper.testInfo.addListener(new GameTestListener() {
            private void cleanup() { if (restored.compareAndSet(false, true)) restore.run(); }
            @Override public void testStructureLoaded(GameTestInfo info) {}
            @Override public void testPassed(GameTestInfo info, GameTestRunner runner) { cleanup(); }
            @Override public void testFailed(GameTestInfo info, GameTestRunner runner) { cleanup(); }
            @Override public void testAddedForRerun(GameTestInfo oldInfo, GameTestInfo newInfo, GameTestRunner runner) { cleanup(); }
        });
    }
}
