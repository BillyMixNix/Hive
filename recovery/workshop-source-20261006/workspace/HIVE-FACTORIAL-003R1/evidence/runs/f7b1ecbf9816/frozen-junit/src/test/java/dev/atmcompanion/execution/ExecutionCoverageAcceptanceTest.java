package dev.atmcompanion.execution;

import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ExecutionCoverageAcceptanceTest {
    private static ExecutionContext.Scan scan(int total, int scanned, int loaded, int unloaded) {
        return new ExecutionContext.Scan(1, total, scanned, loaded, unloaded, 0, false, false, 0, 0);
    }

    @Test void scanCoverageUsesFloorAndCountsUnloadedPositions() {
        assertEquals(0, scan(0, 0, 0, 0).coveragePercent());
        assertEquals(33, scan(3, 1, 0, 1).coveragePercent());
        assertEquals(100, scan(3, 3, 2, 1).coveragePercent());
        assertFalse(scan(3, 3, 2, 1).complete());
    }

    @Test void assessmentReportsUnknownWithoutObservation() {
        assertEquals(-1, ExecutionAssessment.unavailable("not observed").observedCoveragePercent());
    }

    @Test void assessmentProjectsItsOwnScan() {
        var context = new ExecutionContext(ExecutionContext.SCHEMA_VERSION, "2025-01-01T00:00:00Z",
                "minecraft:overworld", scan(4, 3, 2, 1), List.of(), Observation.unavailable("none"), List.of(), List.of());
        var assessment = new ExecutionAssessment("unknown", "", 0, "", List.of(), List.of(), List.of(), List.of(), null, context);
        assertEquals(75, assessment.observedCoveragePercent());
    }
}
