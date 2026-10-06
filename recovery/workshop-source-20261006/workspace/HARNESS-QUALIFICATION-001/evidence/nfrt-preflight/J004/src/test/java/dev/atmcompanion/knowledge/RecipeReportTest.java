package dev.atmcompanion.knowledge;

import com.google.gson.Gson;
import dev.atmcompanion.state.CapabilityStatus;
import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class RecipeReportTest {
    @Test
    void tagAlternativesRemainAChoiceRatherThanFixedIndependentRequirements() {
        var alternatives = new ArrayList<>(List.of("minecraft:oak_planks", "minecraft:birch_planks"));
        var sourceTags = new ArrayList<>(List.of("minecraft:planks", "example_mod:materials/wood"));
        var ingredient = new RecipeReport.Ingredient(0, "runtime_resolved_alternatives", alternatives, sourceTags,
                false, 7, "Source tags preserved; runtime ingredient matching is authoritative");
        alternatives.clear();
        sourceTags.clear();

        assertEquals(List.of("minecraft:oak_planks", "minecraft:birch_planks"), ingredient.alternatives());
        assertEquals(List.of("minecraft:planks", "example_mod:materials/wood"), ingredient.sourceTags());
        assertEquals(0, ingredient.position());
        assertEquals(7, ingredient.matchingItemsInMainInventory());
        assertThrows(UnsupportedOperationException.class, () -> ingredient.alternatives().add("minecraft:stone"));
        assertThrows(UnsupportedOperationException.class, () -> ingredient.sourceTags().clear());
        Gson gson = new Gson();
        assertEquals(ingredient, gson.fromJson(gson.toJson(ingredient), RecipeReport.Ingredient.class));
    }

    @Test
    void unsupportedMachineRequirementsCannotBecomeKnownMissingItems() {
        var candidate = new RecipeReport.Candidate("example:machine_recipe", "example:machine", 1,
                "unsupported", List.of(), Observation.unavailable("Machine energy and fluid inputs have not been inspected"));

        assertEquals(CapabilityStatus.UNAVAILABLE, candidate.inventorySatisfiesIngredients().status());
        assertNull(candidate.inventorySatisfiesIngredients().data());
        assertNotEquals(Observation.available(false), candidate.inventorySatisfiesIngredients());
    }

    @Test
    void truncatedAlternativesAndRecipeResultsRetainTheirUncertaintyFlags() {
        var ingredient = new RecipeReport.Ingredient(0, "runtime_resolved_alternatives", List.of("minecraft:oak_planks"),
                List.of("minecraft:planks"), true, 2, "More alternatives exist than shown");
        var candidate = new RecipeReport.Candidate("example:recipe", "minecraft:crafting", 1, "partial", List.of(ingredient),
                Observation.unavailable("Alternatives were truncated"));
        var report = new RecipeReport("example:output", 10_000, true, List.of(candidate), true, 1);

        assertTrue(report.scanTruncated());
        assertTrue(report.matchesTruncated());
        assertTrue(report.recipes().getFirst().ingredients().getFirst().alternativesTruncated());
        assertEquals(1, report.unreadableRecipes());
        assertEquals(CapabilityStatus.UNAVAILABLE, report.recipes().getFirst().inventorySatisfiesIngredients().status());
    }
}
