package dev.atmcompanion.planning;

import java.util.List;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PlanFormatterStatusLineTest {
    @Test
    void formatsStructuredStatusAndGoalWithoutInventingLabels() {
        var plan = new PlanResult(2, "minecraft:diamond_pickaxe", 2, "blocked",
                List.of(), List.of(), List.of(),
                new PlanResult.Action("obtain", "minecraft:diamond", 3, "", "Missing"),
                List.of(), List.of(), new PlanResult.Metrics(1, 2, 1, false, true, 1), List.of());

        assertEquals("STATUS: blocked | Goal: 2 x minecraft:diamond_pickaxe",
                PlanFormatter.formatStatusLine(plan));
    }
}
