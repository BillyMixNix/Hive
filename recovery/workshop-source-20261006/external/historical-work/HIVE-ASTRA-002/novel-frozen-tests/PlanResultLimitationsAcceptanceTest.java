package dev.atmcompanion.planning;

import dev.atmcompanion.execution.ExecutionAssessment;
import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class PlanResultLimitationsAcceptanceTest {
    @Test void changesOnlyLimitationsAndDefensivelyCopiesThem() {
        var execution = ExecutionAssessment.unavailable("not observed");
        var action = new PlanResult.Action("gather", "minecraft:stone", 2, "recipe", "needed");
        var metrics = new PlanResult.Metrics(7, 9, 2, false, true, 10);
        var plan = new PlanResult(2, "minecraft:stone", 2, "ready", List.of(), List.of(), List.of(),
                action, List.of(), List.of(), metrics, List.of("old"), execution);
        var input = new ArrayList<>(List.of("new", "limited"));
        var changed = plan.withLimitations(input);
        input.add("later");
        assertNotSame(plan, changed);
        assertEquals(List.of("new", "limited"), changed.limitations());
        assertEquals(List.of("old"), plan.limitations());
        assertEquals(plan.goal(), changed.goal());
        assertEquals(plan.quantity(), changed.quantity());
        assertEquals(plan.status(), changed.status());
        assertEquals(plan.selectedPath(), changed.selectedPath());
        assertEquals(action, changed.nextAction());
        assertEquals(plan.alternativePaths(), changed.alternativePaths());
        assertSame(metrics, changed.metrics());
        assertSame(execution, changed.execution());
        assertThrows(UnsupportedOperationException.class, () -> changed.limitations().add("mutate"));
        assertThrows(IllegalArgumentException.class, () -> plan.withLimitations(null));
    }
}
