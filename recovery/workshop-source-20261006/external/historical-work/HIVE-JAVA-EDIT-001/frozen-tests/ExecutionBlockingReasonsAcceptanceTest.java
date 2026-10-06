package dev.atmcompanion.execution;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ExecutionBlockingReasonsAcceptanceTest {
    @Test void mergesDistinctEvidenceInFirstOccurrenceOrder() {
        var assessment = new ExecutionAssessment("unknown", "", 0, "", List.of(), List.of(),
                List.of("locked", "no station", "locked"), List.of("no station", "recipe unverified"), null, null);
        var reasons = assessment.blockingReasons();
        assertEquals(List.of("locked", "no station", "recipe unverified"), reasons);
        assertThrows(UnsupportedOperationException.class, () -> reasons.add("changed"));
        assertEquals(List.of("locked", "no station", "locked"), assessment.blockers());
        var empty = ExecutionAssessment.unnecessary().blockingReasons();
        assertTrue(empty.isEmpty());
        assertThrows(UnsupportedOperationException.class, () -> empty.add("changed"));
    }
}
