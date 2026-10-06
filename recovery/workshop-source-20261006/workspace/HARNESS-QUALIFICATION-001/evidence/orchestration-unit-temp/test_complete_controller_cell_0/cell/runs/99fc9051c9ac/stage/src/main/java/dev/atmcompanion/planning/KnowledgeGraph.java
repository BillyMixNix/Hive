package dev.atmcompanion.planning;

import dev.atmcompanion.knowledge.RecipeIndex;
import dev.atmcompanion.integration.quest.QuestSnapshot;
import dev.atmcompanion.state.Observation;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Bounded inspectable projection of the selected path and observed quests, not a graph database. */
public record KnowledgeGraph(List<Node> nodes, List<Edge> edges, boolean truncated) {
    public static final int MAX_NODES = 512;
    public static final int MAX_EDGES = 1024;
    public KnowledgeGraph { nodes = List.copyOf(nodes); edges = List.copyOf(edges); }
    public record Node(String id, String kind) {}
    public record Edge(String from, String relation, String to, long quantity, String detail) {}
    public static KnowledgeGraph of(RecipeIndex index, PlanResult plan, Observation<QuestSnapshot> quests) {
        Builder graph = new Builder();
        graph.node("item:" + plan.goal(), "ITEM");
        for (var step : plan.selectedPath()) {
            var recipe = index.recipesById().get(step.recipeId());
            if (recipe == null) continue;
            String recipeNode = graph.node("recipe:" + recipe.id(), "RECIPE");
            graph.edge(recipeNode, "PRODUCES", graph.node("item:" + step.output(), "ITEM"), recipe.output().count(),
                    recipe.output().fixed() ? "fixed_recipe_output" : "preview_only");
            for (var requirement : recipe.ingredients()) {
                String requirementNode = graph.node("requirement:" + recipe.id() + "/" + requirement.position(), "REQUIREMENT");
                graph.edge(recipeNode, "REQUIRES", requirementNode, requirement.count(), requirement.kind() + "; alternatives are OR choices");
                for (String tag : requirement.sourceTags()) graph.edge(requirementNode, "SATISFIED_BY", graph.node("tag:" + tag, "TAG"), 1, "tag member, not every member");
                for (String item : requirement.alternatives()) graph.edge(requirementNode, "SATISFIED_BY", graph.node("item:" + item, "ITEM"), 1, "one allowed alternative");
            }
            if (recipe.kind().equals("cooking")) graph.edge(recipeNode, "REQUIRES", graph.node("capability:processing_execution", "CAPABILITY"), 1, "unobserved device/fuel/execution conditions");
        }
        if (quests.data() != null) {
            for (var quest : quests.data().quests().stream().limit(64).toList()) {
                String questNode = graph.node("ftb:" + quest.id(), "QUEST");
                graph.edge(questNode, "DEFINED_IN", graph.node("ftb:" + quest.chapterId(), "CHAPTER"), 0, "Observed containing chapter");
                for (var dependency : quest.dependencies()) graph.edge(questNode, "DEPENDS_ON", graph.node("ftb:" + dependency.id(), dependency.objectType().toUpperCase(java.util.Locale.ROOT)), 0,
                        "FTB dependency edge; logical dependency rule unavailable; use authoritative completion/start flags");
                for (var task : quest.tasks()) {
                    String taskNode = graph.node("ftb:" + task.id(), "TASK");
                    graph.edge(questNode, "HAS_TASK", taskNode, 0, task.type());
                    if (task.itemReference().data() != null) graph.edge(taskNode, "CONFIGURED_REFERENCE", graph.node("item:" + task.itemReference().data().item(), "ITEM"), 0,
                            "Configured item reference only; task matching/filter/component requirements remain unknown");
                }
            }
            if (quests.data().quests().size() > 64) graph.truncated = true;
        } else {
            graph.edge(graph.node("item:" + plan.goal(), "ITEM"), "OBSERVATION_UNAVAILABLE",
                    graph.node("capability:quest_details", "CAPABILITY"), 0, quests.detail());
        }
        return new KnowledgeGraph(new ArrayList<>(graph.nodes.values()), graph.edges, graph.truncated);
    }
    private static final class Builder {
        final Map<String, Node> nodes = new LinkedHashMap<>();
        final List<Edge> edges = new ArrayList<>();
        boolean truncated;
        String node(String id, String kind) {
            if (nodes.containsKey(id)) return id;
            if (nodes.size() >= MAX_NODES) { truncated = true; return null; }
            nodes.put(id, new Node(id, kind)); return id;
        }
        void edge(String from, String relation, String to, long quantity, String detail) {
            if (from == null || to == null || edges.size() >= MAX_EDGES) { truncated = true; return; }
            edges.add(new Edge(from, relation, to, quantity, detail));
        }
    }
}
