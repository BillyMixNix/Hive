package dev.atmcompanion.packtests;

import com.mojang.authlib.GameProfile;
import com.mojang.logging.LogUtils;
import dev.atmcompanion.execution.StationService;
import dev.atmcompanion.knowledge.RecipeIndex;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import dev.atmcompanion.planning.BoundedJson;
import dev.atmcompanion.planning.Goal;
import dev.atmcompanion.planning.PlanningService;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import net.minecraft.SharedConstants;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.neoforged.fml.ModList;
import net.neoforged.fml.loading.FMLLoader;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.common.util.FakePlayerFactory;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import org.slf4j.Logger;

/** Explicitly enabled disposable production-loader probe. Never packaged with the production companion. */
public final class ProductionPackProbe {
    public static final String PROPERTY = "atm_companion.packSmoke", MARKER = "M3-DISPOSABLE-PROBE";
    private static final Logger LOGGER = LogUtils.getLogger();
    private final Path directory;
    private final long began = System.nanoTime();
    private int ticks;
    private boolean finished;
    private ProductionPackProbe(Path directory) { this.directory = directory; }

    public static void registerIfEnabled() {
        Path directory = Path.of("").toAbsolutePath().normalize();
        if (!FMLLoader.isProduction() || !Boolean.getBoolean(PROPERTY)
                || !Files.isRegularFile(directory.resolve(MARKER), LinkOption.NOFOLLOW_LINKS)) return;
        NeoForge.EVENT_BUS.addListener(new ProductionPackProbe(directory)::tick);
        LOGGER.info("ATM Companion disposable production probe explicitly enabled by JVM property and marker");
    }

    private boolean authorized(MinecraftServer server) {
        return Boolean.getBoolean(PROPERTY) && server.isDedicatedServer()
                && server.getServerDirectory().toAbsolutePath().normalize().equals(directory)
                && Files.isRegularFile(directory.resolve(MARKER), LinkOption.NOFOLLOW_LINKS);
    }

    private void tick(ServerTickEvent.Post event) {
        var server = event.getServer();
        // Missing either guard never starts work and never stops a server, including on error paths.
        if (finished || !authorized(server)) return;
        ticks++;
        try {
            var status = RuntimeKnowledge.status(server);
            if (status.state().equals("failed")) throw new IllegalStateException("Pack index failed: " + status.detail());
            if (!status.state().equals("ready")) {
                if (ticks >= 6000) throw new IllegalStateException("Pack index did not become ready within 6000 server ticks: " + status.state() + "/" + status.phase());
                return;
            }
            var evidence = inspect(server);
            evidence.put("terminalStatus", "passed");
            complete(server, evidence, null);
        } catch (RuntimeException | LinkageError failure) {
            var evidence = baseEvidence();
            evidence.put("terminalStatus", "failed");
            evidence.put("errorType", failure.getClass().getName());
            String detail = String.valueOf(failure.getMessage());
            evidence.put("error", detail.substring(0, Math.min(detail.length(), 1000)));
            complete(server, evidence, failure);
        }
    }

    private Map<String, Object> inspect(MinecraftServer server) {
        var index = RuntimeKnowledge.get(server);
        var status = RuntimeKnowledge.status(server);
        require(index.schemaVersion() == 2 && index.generation() == status.generation(), "Wrong or partial index generation");
        require(index.stats().totalRecipes() == server.getRecipeManager().getRecipes().size(), "Recipe source count mismatch");
        require(index.stats().indexedRecipes() <= RecipeIndex.MAX_RECIPES
                && index.coverage().retainedAlternatives() <= RecipeIndex.MAX_TOTAL_ALTERNATIVES
                && index.coverage().retainedIdentities() <= RecipeIndex.MAX_TOTAL_IDENTITIES, "Retained knowledge bounds exceeded");
        var level = server.overworld();
        var player = FakePlayerFactory.get(level, new GameProfile(UUID.nameUUIDFromBytes(
                "atm-companion-disposable-production-probe".getBytes(StandardCharsets.UTF_8)), "atm_prod_probe"));
        player.getInventory().clearContent();
        var origin = level.getSharedSpawnPos();
        player.setPos(origin.getX() + .5, origin.getY() + 1, origin.getZ() + .5);
        var observation = new StationService().scan(player);
        require(observation.stations().size() <= 32 && observation.scan().scannedPositions() <= 4913
                && observation.scan().deepInspections() <= 8 && observation.scan().predicateChecks() <= 4096, "Station observation bounds exceeded");
        require(observation.operation().data() == null, "Shallow scan invented an operation");

        var plans = new ArrayList<Map<String, Object>>();
        var service = new PlanningService();
        for (String goal : List.of("minecraft:diamond_pickaxe", "minecraft:glass", "minecraft:stone")) {
            require(BuiltInRegistries.ITEM.containsKey(ResourceLocation.parse(goal)), "Probe goal is not registered: " + goal);
            var report = service.plan(player, new Goal(goal, 1));
            var plan = report.plan();
            require(plan.metrics().indexGeneration() == index.generation() && plan.metrics().expandedNodes() <= 768, "Plan generation/node bound invalid");
            require(List.of("materials_ready", "blocked", "unsupported", "search_limited").contains(plan.status()), "Empty inventory yielded invalid/already-owned status");
            require(plan.ownedRequirements().isEmpty(), "Empty inventory became invented ownership");
            require(!plan.execution().status().equals("observed_conditions_met"), "Empty inventory became execution ready");
            require(report.questContext().data() == null && report.questContext().detail().contains("not requested"), "Default planning unexpectedly observed quests");
            require(plan.selectedPath().size() <= 768 && plan.missingRequirements().stream().allMatch(r -> r.quantity() > 0), "Malformed or unbounded material result");
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
        for (int slot = 0; slot < 36; slot++) require(player.getInventory().getItem(slot).isEmpty(), "Probe changed disposable inventory");
        var evidence = baseEvidence();
        evidence.put("minecraft", SharedConstants.getCurrentVersion().getName());
        evidence.put("loadedModCount", ModList.get().getMods().size());
        evidence.put("companionVersion", ModList.get().getMods().stream().filter(mod -> mod.getModId().equals("atm_companion")).findFirst().orElseThrow().getVersion().toString());
        evidence.put("indexStatus", status); evidence.put("indexStats", index.stats()); evidence.put("indexCoverage", index.coverage());
        evidence.put("indexComplete", index.complete()); evidence.put("outputItems", index.recipesByOutput().size());
        evidence.put("stationScan", observation.scan()); evidence.put("observedStationCount", observation.stations().size());
        evidence.put("plans", plans);
        return evidence;
    }

    private Map<String, Object> baseEvidence() {
        var evidence = new LinkedHashMap<String, Object>();
        evidence.put("schemaVersion", 1); evidence.put("timestamp", Instant.now().toString());
        evidence.put("scope", "Opt-in disposable production-loader full-server-pack smoke; no graphical client or survival-world playtest");
        evidence.put("observedServerTicks", ticks); evidence.put("probeElapsedMillis", (System.nanoTime() - began) / 1_000_000);
        return evidence;
    }

    private void complete(MinecraftServer server, Map<String, Object> evidence, Throwable failure) {
        if (!authorized(server)) return;
        finished = true;
        try {
            String json = BoundedJson.encode(evidence);
            Files.createDirectories(directory.resolve("evidence"));
            Files.writeString(directory.resolve("evidence/m3-atm10-production-smoke.json"), json, StandardCharsets.UTF_8);
            if (failure == null) LOGGER.info("ATM Companion disposable production probe PASSED; terminal evidence written");
            else LOGGER.error("ATM Companion disposable production probe FAILED; terminal evidence written", failure);
        } catch (Exception writeFailure) {
            LOGGER.error("ATM Companion disposable production probe FAILED to write terminal evidence; success is not established", writeFailure);
        } finally {
            // This shutdown is test-mod behavior and requires the same explicit property+marker guards.
            if (authorized(server)) server.halt(false);
        }
    }
    private static void require(boolean condition, String detail) {
        if (!condition) throw new IllegalStateException(detail);
    }
}
