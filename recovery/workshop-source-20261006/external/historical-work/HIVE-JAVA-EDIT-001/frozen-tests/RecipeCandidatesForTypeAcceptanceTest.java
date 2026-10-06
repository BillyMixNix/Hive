package dev.atmcompanion.knowledge;

import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class RecipeCandidatesForTypeAcceptanceTest {
    @Test void keepsExactEncounterOrderAndReturnsImmutableList() {
        var first = new RecipeReport.Candidate("first", "smelting", 1, "supported", List.of(), Observation.unavailable("not checked"));
        var middle = new RecipeReport.Candidate("middle", "crafting", 1, "supported", List.of(), Observation.unavailable("not checked"));
        var last = new RecipeReport.Candidate("last", "smelting", 1, "unknown", List.of(), Observation.unavailable("not checked"));
        var report = new RecipeReport("minecraft:iron_ingot", 3, false, List.of(first, middle, last), false, 0);
        var selected = report.candidatesForType("smelting");
        assertEquals(List.of(first, last), selected);
        assertThrows(UnsupportedOperationException.class, () -> selected.clear());
        assertTrue(report.candidatesForType("blasting").isEmpty());
        assertEquals(3, report.recipes().size());
        assertThrows(IllegalArgumentException.class, () -> report.candidatesForType(null));
    }
}
