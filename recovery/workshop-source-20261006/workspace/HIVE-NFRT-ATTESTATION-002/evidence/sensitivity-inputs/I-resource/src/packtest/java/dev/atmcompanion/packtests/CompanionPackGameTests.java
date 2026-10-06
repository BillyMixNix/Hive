package dev.atmcompanion.packtests;

import com.mojang.authlib.GameProfile;
import dev.atmcompanion.execution.StationService;
import dev.atmcompanion.knowledge.RecipeIndex;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import dev.atmcompanion.planning.BoundedJson;
import dev.atmcompanion.planning.Goal;
import dev.atmcompanion.planning.PlanningService;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import net.minecraft.SharedConstants;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.resources.ResourceLocation;
import net.neoforged.fml.ModList;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;

/** Inspects actual pack definitions in a disposable server; no recipe replacement or world editing. */
@GameTestHolder("atm_companion_packtests")
@PrefixGameTestTemplate(false)
public final class CompanionPackGameTests {
    @GameTest(template = "empty", batch = "atm_companion_pack_smoke", timeoutTicks = 6000)
    public static void actualPackIndexAndBoundedEmptyInventoryPlanning(GameTestHelper helper) {
        var server = helper.getLevel().getServer();
        helper.startSequence().thenWaitUntil(() -> {
            var status = RuntimeKnowledge.status(server);
            if (status.state().equals("failed")) throw new IllegalStateException("Actual pack indexing failed: " + status.detail());
            helper.assertTrue(status.state().equals("ready"), "Waiting for actual pack staged recipe index: " + status.phase());
        }).thenExecute(() -> {
            var index = RuntimeKnowledge.get(server);
            var status = RuntimeKnowledge.status(server);
            helper.assertTrue(index.schemaVersion() == 2 && index.generation() == status.generation(), "Wrong or partial index generation published");
            helper.assertTrue(index.stats().totalRecipes() == server.getRecipeManager().getRecipes().size(), "Actual pack recipe-manager count differs from index source");
            helper.assertTrue(index.stats().indexedRecipes() <= RecipeIndex.MAX_RECIPES
                    && index.coverage().retainedAlternatives() <= RecipeIndex.MAX_TOTAL_ALTERNATIVES
                    && index.coverage().retainedIdentities() <= RecipeIndex.MAX_TOTAL_IDENTITIES, "Pack index escaped retained-data bounds");
            var player = FakePlayerFactory.get(helper.getLevel(), new GameProfile(
                    UUID.nameUUIDFromBytes("atm-companion-disposable-pack-test".getBytes(StandardCharsets.UTF_8)), "atm_pack_probe"));
            player.getInventory().clearContent();
            var origin = helper.absolutePos(BlockPos.ZERO);
            player.setPos(origin.getX() + .5, origin.getY() + 1, origin.getZ() + .5);
            var observation = new StationService().scan(player);
            helper.assertTrue(observation.stations().size() <= 32 && observation.scan().scannedPositions() <= 4913
                    && observation.scan().deepInspections() <= 8 && observation.scan().predicateChecks() <= 4096,
                    "Actual pack station observation escaped request bounds");
            helper.assertTrue(observation.operation().data() == null, "Shallow station scan invented an operation");

            var plans = new ArrayList<Map<String, Object>>();
            var service = new PlanningService();
            for (String goal : List.of("minecraft:diamond_pickaxe", "minecraft:glass", "minecraft:stone")) {
                helper.assertTrue(BuiltInRegistries.ITEM.containsKey(ResourceLocation.parse(goal)), "Vanilla probe goal is not registered: " + goal);
                var report = service.plan(player, new Goal(goal, 1));
                var plan = report.plan();
                helper.assertTrue(plan.metrics().indexGeneration() == index.generation() && plan.metrics().expandedNodes() <= 768,
                        "Plan used a stale generation or escaped global node cap");
                helper.assertTrue(List.of("materials_ready", "blocked", "unsupported", "search_limited").contains(plan.status()),
                        "Empty inventory produced an invalid/already-owned material status");
                helper.assertTrue(plan.ownedRequirements().isEmpty(), "Empty disposable inventory became invented owned resources");
                helper.assertTrue(!plan.execution().status().equals("observed_conditions_met"), "Empty inventory was treated as a ready nonempty-input operation");
                helper.assertTrue(report.questContext().data() == null && report.questContext().detail().contains("not requested"), "Default probe unexpectedly inspected quests");
                helper.assertTrue(plan.selectedPath().size() <= 768 && plan.missingRequirements().stream().allMatch(r -> r.quantity() > 0),
                        "Malformed or unbounded material result");
                var summary = new LinkedHashMap<String, Object>();
                summary.put("goal", goal); summary.put("materialStatus", plan.status()); summary.put("executionStatus", plan.execution().status());
                summary.put("metrics", plan.metrics()); summary.put("timings", report.timings()); summary.put("nextAction", plan.nextAction());
                summary.put("ownedRequirements", plan.ownedRequirements());
                summary.put("missingCount", plan.missingRequirements().size()); summary.put("missingPreview", plan.missingRequirements().stream().limit(16).toList());
                summary.put("unsupportedCount", plan.unsupportedSteps().size()); summary.put("unsupportedPreview", plan.unsupportedSteps().stream().limit(8).toList());
                summary.put("stepCount", plan.selectedPath().size()); summary.put("recipePreview", plan.selectedPath().stream().limit(12).map(step -> step.recipeId()).toList());
                summary.put("previewLimits", "At most 16 missing entries, 8 unsupported entries and 12 recipe IDs; totals are separate.");
                plans.add(summary);
            }
            for (int slot = 0; slot < 36; slot++) helper.assertTrue(player.getInventory().getItem(slot).isEmpty(), "Probe changed disposable inventory");
            var evidence = new LinkedHashMap<String, Object>();
            evidence.put("schemaVersion", 1); evidence.put("timestamp", Instant.now().toString());
            evidence.put("scope", "Optional disposable full-server-pack compatibility smoke; no graphical client or survival-world playtest");
            evidence.put("minecraft", SharedConstants.getCurrentVersion().getName());
            evidence.put("loadedModCount", ModList.get().getMods().size());
            evidence.put("companionVersion", ModList.get().getMods().stream().filter(mod -> mod.getModId().equals("atm_companion")).findFirst().orElseThrow().getVersion().toString());
            evidence.put("indexStatus", status); evidence.put("indexStats", index.stats()); evidence.put("indexCoverage", index.coverage());
            evidence.put("indexComplete", index.complete()); evidence.put("outputItems", index.recipesByOutput().size());
            evidence.put("stationScan", observation.scan()); evidence.put("observedStationCount", observation.stations().size());
            evidence.put("plans", plans);
            try {
                String json = BoundedJson.encode(evidence);
                helper.assertTrue(json.getBytes(StandardCharsets.UTF_8).length <= BoundedJson.MAX_BYTES, "Smoke evidence exceeded JSON bound");
                Files.createDirectories(Path.of("evidence"));
                Files.writeString(Path.of("evidence/m3-atm10-smoke.json"), json, StandardCharsets.UTF_8);
            } catch (java.io.IOException failure) { throw new IllegalStateException("Could not write disposable pack evidence", failure); }
        }).thenSucceed();
    }
}
