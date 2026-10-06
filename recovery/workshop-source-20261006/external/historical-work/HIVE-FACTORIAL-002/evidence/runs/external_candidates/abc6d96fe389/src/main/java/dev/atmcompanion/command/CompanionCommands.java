package dev.atmcompanion.command;

import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import com.mojang.logging.LogUtils;
import dev.atmcompanion.knowledge.RecipeService;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import dev.atmcompanion.knowledge.IngredientAllocation;
import dev.atmcompanion.integration.quest.QuestService;
import dev.atmcompanion.planning.*;
import dev.atmcompanion.state.GameSnapshot;
import dev.atmcompanion.state.SnapshotFormatter;
import dev.atmcompanion.state.SnapshotJson;
import dev.atmcompanion.state.SnapshotService;
import dev.atmcompanion.activity.ActivityCommandService;
import dev.atmcompanion.activity.LiveActivityService;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.HashMap;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.commands.arguments.ResourceLocationArgument;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.neoforged.fml.loading.FMLPaths;
import org.slf4j.Logger;

public final class CompanionCommands {
    private static final Logger LOGGER = LogUtils.getLogger();
    private static final SnapshotService SNAPSHOTS = new SnapshotService();
    private static final RecipeService RECIPES = new RecipeService();
    private static final PlanningService PLANNER = new PlanningService();
    private static final QuestService QUESTS = new QuestService();
    private static final Map<ServerPlayer, Long> LAST_SNAPSHOT = new WeakHashMap<>();
    private static final Map<ServerPlayer, Long> LAST_RECIPE = new WeakHashMap<>();
    private static final Map<ServerPlayer, Long> LAST_PLANNING = new WeakHashMap<>();
    private static final ActivityCommandService ACTIVITY_SERVICE = new ActivityCommandService(new LiveActivityService());
    private static final int MODS_PER_PAGE = 12;
    private CompanionCommands() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        dispatcher.register(Commands.literal("companion")
                .executes(context -> help(context.getSource()))
                .then(Commands.literal("state").executes(context -> state(context.getSource())))
                .then(Commands.literal("activity")
                    .then(Commands.literal("reset").executes(context -> reset(context.getSource())))
                    .executes(context -> activity(context.getSource())))
                .then(Commands.literal("capabilities").executes(context -> capabilities(context.getSource())))
                .then(Commands.literal("mods").executes(context -> mods(context.getSource(), 1))
                        .then(Commands.argument("page", IntegerArgumentType.integer(1)).executes(context -> mods(context.getSource(), IntegerArgumentType.getInteger(context, "page")))))
                .then(Commands.literal("recipe")
                        .then(Commands.argument("item", ResourceLocationArgument.id()).executes(context -> recipe(context.getSource(), ResourceLocationArgument.getId(context, "item")))))
                .then(Commands.literal("knowledge").executes(context -> knowledge(context.getSource())))
                .then(Commands.literal("stations").executes(context -> stations(context.getSource(), 1))
                        .then(Commands.argument("page", IntegerArgumentType.integer(1)).executes(context -> stations(context.getSource(), IntegerArgumentType.getInteger(context, "page")))))
                .then(Commands.literal("quests").executes(context -> quests(context.getSource())))
                .then(Commands.literal("next").executes(context -> next(context.getSource())))
                .then(Commands.literal("goal").executes(context -> goal(context.getSource(), null))
                        .then(Commands.literal("clear").executes(context -> clearGoal(context.getSource())))
                        .then(Commands.argument("item", ResourceLocationArgument.id())
                                .executes(context -> setGoal(context.getSource(), ResourceLocationArgument.getId(context, "item"), 1))
                                .then(Commands.argument("quantity", IntegerArgumentType.integer(1, 4096))
                                        .executes(context -> setGoal(context.getSource(), ResourceLocationArgument.getId(context, "item"), IntegerArgumentType.getInteger(context, "quantity"))))))
                .then(Commands.literal("debug").requires(source -> source.hasPermission(2))
                        .then(Commands.literal("snapshot").executes(context -> debug(context.getSource())))
                        .then(Commands.literal("plan").executes(context -> debugPlan(context.getSource())))
                        .then(Commands.literal("quests").executes(context -> debugQuests(context.getSource(), 1))
                                .then(Commands.argument("page", IntegerArgumentType.integer(1)).executes(context -> debugQuests(context.getSource(), IntegerArgumentType.getInteger(context, "page")))))
                        .then(Commands.literal("recipes").then(Commands.argument("item", ResourceLocationArgument.id())
                                .executes(context -> debugRecipes(context.getSource(), ResourceLocationArgument.getId(context, "item")))))));
    }
    private static int help(CommandSourceStack source) {
        send(source, "ATM Companion: state | capabilities | mods [page] | recipe <namespace:item> | knowledge | quests");
        send(source, "/companion activity | goal <item> [quantity] | goal | goal clear | next | stations [page]");
        send(source, "Operator exports: debug snapshot | debug plan | debug recipes <item> | debug quests [page]. Server-local; no external services.");
        return 1;
    }
    private static int state(CommandSourceStack source) throws CommandSyntaxException {
        GameSnapshot snapshot = snapshot(source);
        if (snapshot == null) return 0;
        SnapshotFormatter.state(snapshot).forEach(line -> send(source, line));
        return 1;
    }
    private static int capabilities(CommandSourceStack source) throws CommandSyntaxException {
        GameSnapshot snapshot = snapshot(source);
        if (snapshot == null) return 0;
        send(source, "=== COMPANION VISIBILITY ===");
        snapshot.capabilities().entrySet().stream().sorted(Map.Entry.comparingByKey()).limit(32)
                .forEach(entry -> send(source, entry.getKey() + ": " + entry.getValue().status().name().toLowerCase(Locale.ROOT) + " — " + entry.getValue().detail()));
        return 1;
    }
    private static int activity(CommandSourceStack source) throws CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        GameSnapshot snapshot = snapshot(source);
        if (snapshot == null || snapshot.inventory().data() == null) { 
            send(source, "Activity unavailable: inventory was not observed."); 
            return 0; 
        }
        send(source, "=== RECENT ACTIVITY ===");
        List<String> lines = ACTIVITY_SERVICE.observe(player, snapshot);
        if (lines.isEmpty()) {
            send(source, "No inventory changes since the previous activity check.");
        } else {
            lines.forEach(line -> send(source, line));
        }
        return 1;
    }

    private static int reset(CommandSourceStack source) throws CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        String playerId = player.getGameProfile().getName();
        String response = ACTIVITY_SERVICE.reset(playerId);
        send(source, response);
        return 1;
    }
    private static int mods(CommandSourceStack source, int page) throws CommandSyntaxException {
        GameSnapshot snapshot = snapshot(source);
        if (snapshot == null) return 0;
        if (snapshot.modpack().data() == null) {
            send(source, "Installed mods: unavailable; " + snapshot.modpack().detail());
            return 0;
        }
        var environment = snapshot.modpack().data();
        int pages = Math.max(1, (environment.mods().size() + MODS_PER_PAGE - 1) / MODS_PER_PAGE);
        if (page > pages) { send(source, "Page must be between 1 and " + pages); return 0; }
        send(source, "Loaded runtime mods: " + environment.totalMods() + "; page " + page + "/" + pages + (environment.truncated() ? " (list truncated)" : ""));
        environment.mods().stream().skip((long) (page - 1) * MODS_PER_PAGE).limit(MODS_PER_PAGE)
                .forEach(mod -> send(source, mod.id() + " " + mod.version()));
        if (page < pages) send(source, "Next: /companion mods " + (page + 1));
        return 1;
    }
    private static int debug(CommandSourceStack source) throws CommandSyntaxException {
        GameSnapshot snapshot = snapshot(source);
        if (snapshot == null) return 0;
        Path directory = FMLPaths.CONFIGDIR.get().resolve("atm_companion");
        Path temporary = directory.resolve("latest-snapshot.json.tmp");
        try {
            String json = SnapshotJson.toJson(snapshot);
            Files.createDirectories(directory);
            Files.writeString(temporary, json, StandardCharsets.UTF_8);
            Path destination = directory.resolve("latest-snapshot.json");
            try { Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
            catch (AtomicMoveNotSupportedException ignored) { Files.move(temporary, destination, StandardCopyOption.REPLACE_EXISTING); }
            send(source, "Wrote server-local config/atm_companion/latest-snapshot.json; includes your current location/inventory and replaces the previous export.");
            return 1;
        } catch (IOException | RuntimeException exception) {
            LOGGER.error("ATM Companion could not write bounded debug snapshot", exception);
            source.sendFailure(Component.literal("Snapshot export failed: " + exception.getClass().getSimpleName() + "; see server log."));
            return 0;
        }
    }
    private static int recipe(CommandSourceStack source, ResourceLocation output) throws CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        SnapshotService.requireServerThread(player);
        if (!allow(player, LAST_RECIPE, 5_000_000_000L)) {
            send(source, "Please wait 5 seconds between recipe queries.");
            return 0;
        }
        try {
            if (!BuiltInRegistries.ITEM.containsKey(output)) { send(source, "Unknown registered item: " + output); return 0; }
            var index = RuntimeKnowledge.get(player.getServer());
            var routes = index.recipesFor(output.toString());
            send(source, "Recipe knowledge: " + output + " | indexed routes/previews: " + index.outputRecipeCounts().getOrDefault(output.toString(), 0) + " | generation " + index.generation());
            if (routes.isEmpty()) send(source, "No indexed output route found; unknown/dynamic outputs may still produce this item.");
            for (var candidate : routes.stream().limit(3).toList()) {
                send(source, candidate.id() + " [" + candidate.type() + "] -> " + candidate.output().count() + " item(s)" + (candidate.output().fixed() ? "" : " (preview only)"));
                if (!candidate.dependencySupported()) {
                    send(source, "  Planning unavailable: " + String.join("; ", candidate.limitations()));
                    continue;
                }
                Map<String, IngredientGroup> grouped = new LinkedHashMap<>();
                List<List<Integer>> matchingSlots = new ArrayList<>();
                Map<Integer, Integer> counts = new HashMap<>();
                for (int slot = 0; slot < 36; slot++) counts.put(slot, player.getInventory().getItem(slot).getCount());
                for (var requirement : candidate.ingredients()) {
                    String key = requirement.kind() + requirement.sourceItems() + requirement.sourceTags();
                    var previous = grouped.get(key);
                    List<Integer> matches = new ArrayList<>();
                    long have = 0;
                    for (int slot = 0; slot < 36; slot++) {
                        var stack = player.getInventory().getItem(slot);
                        if (!stack.isEmpty() && requirement.alternatives().contains(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString())) {
                            matches.add(slot); have += stack.getCount();
                        }
                    }
                    for (int i = 0; i < requirement.count(); i++) matchingSlots.add(matches);
                    String label = requirement.kind().equals("tag") ? "#" + String.join(" OR #", requirement.sourceTags())
                            : String.join(" OR ", requirement.alternatives().stream().limit(3).toList()) + (requirement.alternatives().size() > 3 ? " OR ..." : "");
                    grouped.put(key, new IngredientGroup(label, (previous == null ? 0 : previous.quantity()) + requirement.count(), have));
                }
                grouped.values().stream().limit(5).forEach(g -> send(source, "  " + g.quantity() + " x (" + g.label() + ") | have matching: " + g.have()));
                if (grouped.size() > 5) send(source, "  Additional ingredient groups omitted.");
                boolean sufficient = matchingSlots.size() <= 9 && IngredientAllocation.canSatisfy(matchingSlots, counts);
                send(source, "  One-operation inputs: " + (sufficient ? "present" : "missing") + "; overlapping choices allocated once.");
                send(source, "  Execution unverified: " + String.join("; ", candidate.limitations()));
            }
            if (index.outputRecipeCounts().getOrDefault(output.toString(), 0) > 3) send(source, "More routes omitted; operator JSON: /companion debug recipes " + output);
            if (!index.complete()) send(source, "Index has unknown/truncated outputs. Material availability does not establish overall craftability.");
            return 1;
        } catch (RuntimeException | LinkageError exception) {
            if (exception instanceof RuntimeKnowledge.IndexUnavailableException) return planningFailure(source, exception);
            LOGGER.warn("ATM Companion recipe query failed for {}", output, exception);
            source.sendFailure(Component.literal(SnapshotFormatter.boundLine("Recipe query unavailable: " + exception.getClass().getSimpleName() + "; check item ID and server log.")));
            return 0;
        }
    }
    private record IngredientGroup(String label, int quantity, long have) {}

    private static int setGoal(CommandSourceStack source, ResourceLocation item, int quantity) throws CommandSyntaxException {
        try { return goal(source, new Goal(item.toString(), quantity)); }
        catch (IllegalArgumentException exception) { send(source, "Invalid goal: " + exception.getMessage()); return 0; }
    }

    private static int knowledge(CommandSourceStack source) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        try {
            var progress = RuntimeKnowledge.status(player.getServer());
            if (!progress.state().equals("ready")) {
                send(source, "Recipe index " + progress.state() + " | generation " + progress.generation() + " | phase " + progress.phase());
                send(source, "Visited " + progress.visitedDefinitions() + "/" + progress.totalDefinitions() + "; normalized " + progress.normalizedDefinitions() + "; slices " + progress.slices());
                send(source, progress.detail());
                return 1;
            }
            var index = RuntimeKnowledge.get(player.getServer());
            var stats = index.stats();
            send(source, "Recipe index generation " + index.generation() + ": " + stats.indexedRecipes() + "/" + stats.totalRecipes() + " definitions, " + index.recipesByOutput().size() + " item outputs");
            send(source, "Unsupported material models: " + stats.unsupportedRecipes() + "; unknown/nonfixed outputs: " + stats.unknownOutputs() + "; build: " + stats.buildMillis() + " ms");
            send(source, "Coverage complete: " + index.complete() + "; slices " + index.coverage().slices() + "; active " + index.coverage().activeMillis() + " ms; max slice " + index.coverage().maxSliceMillis() + " ms (cooperative)");
            var types = new java.util.TreeMap<String, Integer>();
            index.recipesById().values().forEach(r -> types.merge(r.type(), 1, Integer::sum));
            types.entrySet().stream().limit(6).forEach(e -> send(source, "  " + e.getKey() + ": " + e.getValue()));
            if (types.size() > 6) send(source, "+ " + (types.size() - 6) + " other recipe types");
            return 1;
        } catch (RuntimeException | LinkageError exception) { return planningFailure(source, exception); }
    }
    private static int stations(CommandSourceStack source, int page) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        try {
            var context = new dev.atmcompanion.execution.StationService().scan(player);
            int pages = Math.max(1, (context.stations().size() + 4) / 5);
            if (page > pages) { send(source, "Station page must be 1.." + pages); return 0; }
            var scan = context.scan();
            send(source, "Nearby vanilla stations | page " + page + "/" + pages + " | radius 8 cube | coverage " + (scan.complete() ? "complete" : "partial"));
            context.stations().stream().skip((page - 1L) * 5).limit(5).forEach(s -> send(source,
                    s.blockId() + " " + s.x() + "/" + s.y() + "/" + s.z() + " | " + (s.withinReach() ? "within reach" : "outside reach") + " | vanilla interaction " + s.vanillaMayInteract()));
            if (context.stations().isEmpty()) send(source, "No supported station observed in the scanned positions.");
            send(source, "Scanned " + scan.scannedPositions() + "/" + scan.totalPositions() + "; unloaded " + scan.unloadedPositions() + "; discovered " + scan.discoveredStations());
            send(source, "Nearest 32 retained. Claims, safe access and ownership unverified; goal/next inspect the selected operation.");
            return 1;
        } catch (RuntimeException | LinkageError exception) { return planningFailure(source, exception); }
    }
    private static int goal(CommandSourceStack source, Goal requested) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        try {
            var saved = GoalSavedData.get(player.getServer());
            if (requested != null) {
                if (!BuiltInRegistries.ITEM.containsKey(ResourceLocation.parse(requested.item()))) { send(source, "Unknown registered item: " + requested.item()); return 0; }
                saved.set(player.getUUID(), requested);
            }
            Goal current = saved.goal(player.getUUID());
            if (current == null) { send(source, "No current goal. Set one with /companion goal <namespace:item> [quantity]"); return 0; }
            var report = PLANNER.plan(player, current);
            PlanFormatter.format(report.plan()).forEach(line -> send(source, line));
            return 1;
        } catch (RuntimeException | LinkageError exception) { return planningFailure(source, exception); }
    }
    private static int clearGoal(CommandSourceStack source) throws CommandSyntaxException {
        var player = source.getPlayerOrException();
        SnapshotService.requireServerThread(player);
        GoalSavedData.get(player.getServer()).clear(player.getUUID());
        send(source, "Current goal cleared.");
        return 1;
    }
    private static int quests(CommandSourceStack source) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        return showQuests(source, PlanningService.overviewContext(QUESTS.summary(player)), false);
    }
    private static int showQuests(CommandSourceStack source, dev.atmcompanion.state.Observation<PlanningReport.QuestContext> context, boolean alternative) {
        if (context.data() == null) { send(source, "Quest visibility: " + context.status().name().toLowerCase(Locale.ROOT) + "; " + context.detail()); return 0; }
        var quests = context.data();
        send(source, "FTB team quests: completed " + quests.completed() + " | available incomplete " + quests.available() + " | blocked/hidden/locked " + quests.blocked());
        if (quests.options().isEmpty()) send(source, "No currently available incomplete quest was observed.");
        quests.options().stream().limit(alternative ? 1 : 5).forEach(q -> send(source, (alternative ? "Alternative available quest: " : "  ") + q.title() + " [" + q.id() + "]"));
        send(source, "Quest ordering: ascending ID, not strategic ranking; completed repeatable quests are excluded.");
        return 1;
    }
    private static int next(CommandSourceStack source) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        try {
            Goal current = GoalSavedData.get(player.getServer()).goal(player.getUUID());
            if (current == null) {
                send(source, "No item goal is set. These are observed quest options:");
                return showQuests(source, PlanningService.overviewContext(QUESTS.summary(player)), true);
            }
            var report = PLANNER.planForNext(player, current);
            var action = report.plan().nextAction();
            send(source, "NEXT for " + current.item() + ": " + action.kind() + " " + action.quantity() + " x " + action.item());
            send(source, "Why: " + action.reason());
            send(source, "Materials: " + report.plan().status() + "; next operation: " + report.plan().execution().status() + "; modded access and future operations unverified.");
            if (report.plan().metrics().searchTruncated()) send(source, "Search was limited; this is the selected discovered path.");
            showQuests(source, report.questContext(), true);
            return 1;
        } catch (RuntimeException | LinkageError exception) { return planningFailure(source, exception); }
    }
    private static int debugPlan(CommandSourceStack source) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        try {
            Goal goal = GoalSavedData.get(player.getServer()).goal(player.getUUID());
            if (goal == null) { send(source, "Set a goal before exporting a plan."); return 0; }
            return writeDebug(source, "latest-plan.json", PLANNER.plan(player, goal, true));
        } catch (RuntimeException | LinkageError exception) { return planningFailure(source, exception); }
    }
    private static int debugRecipes(CommandSourceStack source, ResourceLocation item) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        try {
            if (!BuiltInRegistries.ITEM.containsKey(item)) { send(source, "Unknown registered item: " + item); return 0; }
            var index = RuntimeKnowledge.get(player.getServer());
            return writeDebug(source, "latest-recipes.json", Map.of("schemaVersion", 2, "item", item.toString(),
                    "generation", index.generation(), "statistics", index.stats(), "indexComplete", index.complete(),
                    "routesTruncated", index.recipesForTruncated(item.toString()), "recipes", index.recipesFor(item.toString())));
        } catch (RuntimeException | LinkageError exception) { return planningFailure(source, exception); }
    }
    private static int writeDebug(CommandSourceStack source, String filename, Object dto) {
        Path directory = FMLPaths.CONFIGDIR.get().resolve("atm_companion");
        try {
            String json = BoundedJson.encode(dto);
            Files.createDirectories(directory);
            Path temp = directory.resolve(filename + ".tmp");
            Files.writeString(temp, json, StandardCharsets.UTF_8);
            try { Files.move(temp, directory.resolve(filename), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
            catch (AtomicMoveNotSupportedException ignored) { Files.move(temp, directory.resolve(filename), StandardCopyOption.REPLACE_EXISTING); }
            send(source, "Wrote server-local config/atm_companion/" + filename + "; replaced previous export.");
            return 1;
        } catch (IOException | RuntimeException exception) { return planningFailure(source, exception); }
    }
    private static int debugQuests(CommandSourceStack source, int page) throws CommandSyntaxException {
        var player = planningPlayer(source);
        if (player == null) return 0;
        var observed = QUESTS.snapshot(player);
        if (observed.data() == null) { send(source, "Quest export unavailable: " + observed.detail()); return 0; }
        var book = observed.data();
        int pages = Math.max(1, (book.quests().size() + 7) / 8);
        if (page > pages) { send(source, "Quest page must be 1.." + pages); return 0; }
        var selected = book.quests().stream().sorted(java.util.Comparator.comparing(dev.atmcompanion.integration.quest.QuestSnapshot.Quest::id)).skip((long)(page - 1) * 8).limit(8).toList();
        var chapterIds = selected.stream().map(dev.atmcompanion.integration.quest.QuestSnapshot.Quest::chapterId).collect(java.util.stream.Collectors.toSet());
        return writeDebug(source, "latest-quests.json", Map.of("schemaVersion", 1, "timestamp", book.timestamp(), "scope", book.progressScope(),
                "teamLocked", book.teamLocked(), "totalQuests", book.quests().size(), "page", page, "pages", pages, "availabilityRule", book.availabilityRule(),
                "quests", selected, "chapters", book.chapters().stream().filter(c -> chapterIds.contains(c.id())).toList()));
    }
    private static ServerPlayer planningPlayer(CommandSourceStack source) throws CommandSyntaxException {
        var player = source.getPlayerOrException();
        SnapshotService.requireServerThread(player);
        if (!allow(player, LAST_PLANNING, 2_000_000_000L)) { send(source, "Please wait 2 seconds between knowledge/planning/quest commands."); return null; }
        return player;
    }
    private static int planningFailure(CommandSourceStack source, Throwable exception) {
        if (exception instanceof RuntimeKnowledge.IndexUnavailableException) {
            var progress = RuntimeKnowledge.status(source.getServer());
            send(source, "Recipe index " + progress.state() + ": " + progress.detail());
            if (progress.state().equals("building") || progress.state().equals("recovering"))
                send(source, "Keep the world running; check /companion knowledge, then retry this command when the index is ready.");
            else send(source, "Check /companion knowledge and the server log for the cause; a completed /reload starts a fresh indexing attempt.");
            return 0;
        }
        LOGGER.warn("ATM Companion knowledge/planning operation unavailable", exception);
        source.sendFailure(Component.literal("Knowledge/plan unavailable: " + exception.getClass().getSimpleName() + "; see server log."));
        return 0;
    }
    private static GameSnapshot snapshot(CommandSourceStack source) throws CommandSyntaxException {
        ServerPlayer player = source.getPlayerOrException();
        SnapshotService.requireServerThread(player);
        if (!allow(player, LAST_SNAPSHOT, 1_000_000_000L)) {
            send(source, "Please wait 1 second between snapshot commands.");
            return null;
        }
        try { return SNAPSHOTS.capture(player); }
        catch (RuntimeException | LinkageError exception) {
            LOGGER.error("ATM Companion snapshot failed", exception);
            source.sendFailure(Component.literal("Snapshot unavailable: " + exception.getClass().getSimpleName() + "; see server log."));
            return null;
        }
    }
    private static boolean allow(ServerPlayer player, Map<ServerPlayer, Long> lastCalls, long minimumNanos) {
        long now = System.nanoTime();
        Long previous = lastCalls.get(player);
        if (previous != null && now - previous < minimumNanos) return false;
        lastCalls.put(player, now);
        return true;
    }
    private static void send(CommandSourceStack source, String message) {
        source.sendSuccess(() -> Component.literal(SnapshotFormatter.boundLine(message)), false);
    }
}
