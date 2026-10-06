package dev.atmcompanion.planning;

import com.google.gson.JsonParser;
import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.stream.IntStream;

import static dev.atmcompanion.knowledge.RecipeFixtures.*;
import static org.junit.jupiter.api.Assertions.*;

class PlanningOutputTest {
    @Test
    void publishedPlanHasVersionedStructuredFactsAndBoundedChat() {
        var inputs = IntStream.range(0, 64).mapToObj(i -> exact(i, "fixture:item_" + i, 1))
                .toArray(NormalizedRecipe.Requirement[]::new);
        var plan = new DeterministicPlanner().plan(index(recipe("fixture:goal", "fixture:goal", 1, inputs)),
                "fixture:goal", 1, Map.of());
        var lines = PlanFormatter.format(plan);

        assertTrue(lines.size() <= PlanFormatter.MAX_LINES);
        assertTrue(lines.stream().allMatch(line -> line.length() <= 240));
        assertTrue(lines.stream().anyMatch(line -> line.contains("other missing types")));
        assertTrue(lines.stream().anyMatch(line -> line.contains("execution") && line.contains("unverified")));
        String json = BoundedJson.encode(plan);
        var root = JsonParser.parseString(json).getAsJsonObject();
        assertEquals(2, root.get("schemaVersion").getAsInt());
        assertEquals(64, root.getAsJsonArray("missingRequirements").size());
        assertTrue(json.getBytes(StandardCharsets.UTF_8).length <= BoundedJson.MAX_BYTES);
    }

    @Test
    void debugJsonRejectsBothAsciiCharacterOverflowAndMultibyteByteOverflow() {
        assertThrows(IllegalArgumentException.class, () -> BoundedJson.encode(Map.of("text", "x".repeat(BoundedJson.MAX_BYTES + 1))));
        String multibyte = "€".repeat(BoundedJson.MAX_BYTES / 3 + 1);
        assertTrue(multibyte.length() < BoundedJson.MAX_BYTES);
        assertThrows(IllegalArgumentException.class, () -> BoundedJson.encode(Map.of("text", multibyte)));
    }

    @Test
    void boundedGraphKeepsOnlyEdgesWhoseEndpointsExistAndMarksOmission() {
        var inputs = IntStream.range(0, 4).mapToObj(position -> choice(position, 1,
                IntStream.range(0, 256).mapToObj(i -> "fixture:material_" + position + "_" + i).toArray(String[]::new)))
                .toArray(NormalizedRecipe.Requirement[]::new);
        var index = index(recipe("fixture:goal", "fixture:goal", 1, inputs));
        var plan = new PlanResult(1, "fixture:goal", 1, "blocked", List.of(), List.of(),
                List.of(new PlanResult.Step("fixture:goal", "fixture:goal", 1, 1, "minecraft:crafting", 0, List.of())),
                new PlanResult.Action("inspect", "fixture:goal", 1, "", "Fixture"), List.of(), List.of(),
                new PlanResult.Metrics(7, 1, 0, false, true, 1), List.of());
        var graph = KnowledgeGraph.of(index, plan, Observation.notIntegrated("No quests"));
        var nodeIds = graph.nodes().stream().map(KnowledgeGraph.Node::id).collect(java.util.stream.Collectors.toSet());

        assertTrue(graph.truncated());
        assertTrue(graph.nodes().size() <= KnowledgeGraph.MAX_NODES);
        assertTrue(graph.edges().size() <= KnowledgeGraph.MAX_EDGES);
        assertTrue(graph.edges().stream().allMatch(edge -> nodeIds.contains(edge.from()) && nodeIds.contains(edge.to())));
        assertTrue(graph.edges().stream().filter(edge -> edge.relation().equals("REQUIRES"))
                .allMatch(edge -> edge.detail().contains("OR choices")));
    }

    @Test
    void goalPersistsOnlyBoundedRegistryIdentityAndQuantity() {
        assertEquals("mekanism:metallurgic_infuser", new Goal("mekanism:metallurgic_infuser", 1).item());
        assertThrows(IllegalArgumentException.class, () -> new Goal("display name", 1));
        assertThrows(IllegalArgumentException.class, () -> new Goal("minecraft:stone", 0));
        assertThrows(IllegalArgumentException.class, () -> new Goal("minecraft:stone", 4097));
        assertThrows(IllegalArgumentException.class, () -> new Goal("fixture:" + "x".repeat(256), 1));
    }

    @Test
    void graphDistinguishesOmittedQuestDetailsFromAnObservedEmptyQuestBook() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, exact(0, "fixture:material", 1)));
        var plan = new DeterministicPlanner().plan(index, "fixture:goal", 1, Map.of());
        String reason = "Quest overview requested; detailed task and dependency graph were not collected";
        var unavailable = KnowledgeGraph.of(index, plan, Observation.unavailable(reason));
        assertTrue(unavailable.edges().stream().anyMatch(edge -> edge.relation().equals("OBSERVATION_UNAVAILABLE")
                && edge.to().equals("capability:quest_details") && edge.detail().equals(reason)));
        var empty = new dev.atmcompanion.integration.quest.QuestSnapshot(1, "2026-09-22T12:34:56Z", "2101.1.36",
                dev.atmcompanion.integration.quest.QuestSnapshot.TEAM_SCOPE, false, List.of(), List.of(), List.of(),
                dev.atmcompanion.integration.quest.QuestSnapshot.AVAILABILITY_RULE);
        var knownEmpty = KnowledgeGraph.of(index, plan, Observation.available(empty));
        assertFalse(knownEmpty.edges().stream().anyMatch(edge -> edge.to().equals("capability:quest_details")));
    }
}
