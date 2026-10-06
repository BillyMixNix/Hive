package dev.atmcompanion.planning;

import dev.atmcompanion.integration.quest.QuestService;
import dev.atmcompanion.integration.quest.QuestSnapshot;
import dev.atmcompanion.integration.quest.QuestOverview;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import dev.atmcompanion.state.Observation;
import dev.atmcompanion.state.SnapshotService;
import java.time.Instant;
import java.util.Map;
import java.util.TreeMap;
import java.util.List;
import java.util.ArrayList;
import java.util.Comparator;
import dev.atmcompanion.execution.*;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;

public final class PlanningService {
    private final DeterministicPlanner planner = new DeterministicPlanner();
    private final QuestService quests = new QuestService();
    private final StationService stations;
    public PlanningService() { this(new StationService()); }
    /** Harness seam; production always uses the real shared cooperative observation budget. */
    public PlanningService(StationService stations) { this.stations = java.util.Objects.requireNonNull(stations); }
    public PlanningReport plan(ServerPlayer player, Goal goal) {
        return plan(player, goal, false);
    }
    public PlanningReport plan(ServerPlayer player, Goal goal, boolean includeQuests) {
        return plan(player, goal, includeQuests, true);
    }
    /** Chat needs fresh quest counts/options, while operator exports retain the detailed query. */
    public PlanningReport planForNext(ServerPlayer player, Goal goal) {
        return plan(player, goal, true, false);
    }
    private PlanningReport plan(ServerPlayer player, Goal goal, boolean includeQuests, boolean questDetails) {
        long began = System.nanoTime();
        SnapshotService.requireServerThread(player);
        var id = ResourceLocation.parse(goal.item());
        if (!BuiltInRegistries.ITEM.containsKey(id)) throw new IllegalArgumentException("Goal item is no longer registered: " + goal.item());
        var index = RuntimeKnowledge.get(player.getServer());
        Map<String, Long> inventory = new TreeMap<>();
        for (int slot = 0; slot < 36; slot++) {
            var stack = player.getInventory().getItem(slot);
            if (!stack.isEmpty()) inventory.merge(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), (long) stack.getCount(), Long::sum);
        }
        long materialsBegan = System.nanoTime();
        var candidates = planner.planCandidates(index, goal.item(), goal.quantity(), inventory);
        long materialNanos = System.nanoTime() - materialsBegan;
        long executionBegan = System.nanoTime();
        List<PlanResult> assessed = new ArrayList<>();
        // One command shares a single finite discovery/inspection budget across every retained path.
        StationService.Session session = null;
        for (var candidate : candidates) {
            if (candidate.status().equals("already_owned")) {
                assessed.add(candidate.withExecution(ExecutionAssessment.unnecessary())); continue;
            }
            if (candidate.selectedPath().isEmpty() || !candidate.unsupportedSteps().isEmpty()) {
                assessed.add(candidate.withExecution(ExecutionAssessment.unavailable("No supported next operation on this material path"))); continue;
            }
            var step = candidate.selectedPath().getFirst();
            var recipe = index.recipesById().get(step.recipeId());
            if (recipe == null) { assessed.add(candidate.withExecution(ExecutionAssessment.unavailable("Selected recipe is not indexed"))); continue; }
            var inputs = OperationInputs.select(recipe, step, inventory);
            if (session == null) session = stations.begin(player);
            Map<String, Long> reserved = new TreeMap<>();
            candidate.ownedRequirements().forEach(r -> reserved.merge(r.item(), r.quantity(), Long::sum));
            int inputSlot = -1;
            if (inputs.ready() && inputs.inputs().size() == 1) {
                String selected = inputs.inputs().getFirst().item();
                for (int slot = 0; slot < 36; slot++) {
                    var stack = player.getInventory().getItem(slot);
                    if (!stack.isEmpty() && BuiltInRegistries.ITEM.getKey(stack.getItem()).toString().equals(selected)) { inputSlot = slot; break; }
                }
            }
            var observation = session.capture(recipe, reserved, inputSlot);
            assessed.add(candidate.withExecution(ExecutionAssessor.assess(candidate, recipe, inputs, observation)));
        }
        assessed.sort(Comparator.comparingInt((PlanResult p) -> p.unsupportedSteps().size())
                .thenComparingLong(p -> p.missingRequirements().stream().mapToLong(PlanResult.Resource::quantity).sum())
                .thenComparingInt(p -> ExecutionAssessor.rank(p.execution().status()))
                .thenComparingInt(p -> p.metrics().depth()).thenComparingInt(p -> p.selectedPath().size())
                .thenComparing(p -> p.selectedPath().toString()));
        PlanResult selected = assessed.getFirst();
        PlanResult plan = selected.withAlternatives(assessed.stream().skip(1).limit(5).map(p -> new PlanResult.Alternative(
                p.selectedPath().isEmpty() ? "" : p.selectedPath().getLast().recipeId(),
                p.missingRequirements().stream().mapToLong(PlanResult.Resource::quantity).sum(), p.unsupportedSteps().size(), p.selectedPath().size(),
                p.missingRequirements().stream().limit(8).toList(), p.unsupportedSteps().stream().limit(8).toList(), p.nextAction(), p.execution().status())).toList());
        long executionNanos = System.nanoTime() - executionBegan;
        long questBegan = System.nanoTime();
        Observation<QuestSnapshot> observed = includeQuests && questDetails ? quests.snapshot(player)
                : Observation.unavailable(includeQuests ? "Quest overview requested; task, dependency and detailed progress graph were not collected"
                        : "Quest scan not requested; use /companion quests or /companion next");
        var questContext = includeQuests && !questDetails ? overviewContext(quests.summary(player)) : context(observed);
        long questNanos = System.nanoTime() - questBegan;
        var graph = KnowledgeGraph.of(index, plan, observed);
        return new PlanningReport(2, Instant.now().toString(), plan, questContext, graph,
                new PlanningReport.Timings(materialNanos, executionNanos, questNanos, System.nanoTime() - began));
    }
    public static Observation<PlanningReport.QuestContext> overviewContext(Observation<QuestOverview> observation) {
        if (observation.data() == null) return new Observation<>(observation.status(), null, observation.detail());
        var data = observation.data();
        return Observation.available(new PlanningReport.QuestContext(data.progressScope(), data.questCount(),
                data.completedQuests(), data.availableQuests(), data.questCount() - data.completedQuests() - data.availableQuests(),
                data.options().stream().map(q -> new PlanningReport.QuestOption(q.id(), q.title())).toList(),
                "Ascending FTB quest ID; available does not mean strategically best. Hidden and locked incomplete quests count as blocked. " + data.detail()));
    }
    public static Observation<PlanningReport.QuestContext> context(Observation<QuestSnapshot> observation) {
        if (observation.data() == null) return new Observation<>(observation.status(), null, observation.detail());
        var data = observation.data();
        int completed = (int) data.quests().stream().filter(QuestSnapshot.Quest::completed).count();
        var availableIds = new java.util.HashSet<>(data.availableQuestIds());
        var options = data.quests().stream().filter(q -> availableIds.contains(q.id())).sorted(java.util.Comparator.comparing(QuestSnapshot.Quest::id))
                .limit(5).map(q -> new PlanningReport.QuestOption(q.id(), q.title())).toList();
        return Observation.available(new PlanningReport.QuestContext(data.progressScope(), data.quests().size(), completed, data.availableQuestIds().size(),
                data.quests().size() - completed - data.availableQuestIds().size(), options, "Ascending FTB quest ID; available does not mean strategically best. Hidden and locked incomplete quests count as blocked."));
    }
}
