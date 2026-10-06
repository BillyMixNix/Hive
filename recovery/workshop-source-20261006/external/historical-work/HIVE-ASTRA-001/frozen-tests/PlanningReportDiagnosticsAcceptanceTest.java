package dev.atmcompanion.planning;

import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class PlanningReportDiagnosticsAcceptanceTest {
    private PlanResult plan(List<String> limitations, boolean searchTruncated, boolean indexComplete) {
        var metrics = new PlanResult.Metrics(1, 20, 3, searchTruncated, indexComplete, 50L);
        var action = new PlanResult.Action("inspect_step", "minecraft:iron_ingot", 1, "recipe:iron", "inspect");
        return new PlanResult(2, "minecraft:iron_ingot", 1, "ready", List.of(), List.of(), List.of(),
                action, List.of(), List.of(), metrics, limitations);
    }

    @Test
    void composesDeduplicatesBoundsAndPreservesUnknownsInStableOrder() {
        var report = new PlanningReport(1, "2026-09-30T12:00:00Z",
                plan(List.of("Plan caveat", "Shared caveat", "Plan caveat"), true, false),
                Observation.unavailable("FTB probe unavailable"),
                new KnowledgeGraph(List.of(), List.of(), true));

        var diagnostics = report.diagnostics();
        assertEquals(List.of(
                "Plan caveat",
                "Shared caveat",
                "Planning search was truncated.",
                "Recipe index is incomplete.",
                "Quest context unavailable (UNAVAILABLE): FTB probe unavailable",
                "Knowledge graph is truncated; some nodes or edges were omitted."
        ), diagnostics);
        assertThrows(UnsupportedOperationException.class, () -> diagnostics.add("mutate"));
    }

    @Test
    void capsAtSixteenAfterStableDeDuplicationAndAddsNoFalseCaveats() {
        var limitations = java.util.stream.IntStream.range(0, 20).mapToObj(i -> "limit-" + i).toList();
        var report = new PlanningReport(1, "2026-09-30T12:00:00Z",
                plan(limitations, false, true),
                Observation.available(new PlanningReport.QuestContext("team", 0, 0, 0, 0, List.of(), "id")),
                new KnowledgeGraph(List.of(), List.of(), false));

        var diagnostics = report.diagnostics();
        assertEquals(16, diagnostics.size());
        assertEquals("limit-0", diagnostics.getFirst());
        assertEquals("limit-15", diagnostics.getLast());
        assertFalse(diagnostics.stream().anyMatch(x -> x.startsWith("Quest context unavailable")));
    }
}
