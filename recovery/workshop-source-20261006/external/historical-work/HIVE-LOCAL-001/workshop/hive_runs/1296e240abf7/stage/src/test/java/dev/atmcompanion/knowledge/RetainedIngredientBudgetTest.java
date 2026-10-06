package dev.atmcompanion.knowledge;

import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.IntStream;
import static dev.atmcompanion.knowledge.RecipeFixtures.*;
import static org.junit.jupiter.api.Assertions.*;

class RetainedIngredientBudgetTest {
    @Test
    void repeatedIncompleteExpansionsDoNotStarveLaterExactMaterials() {
        var wide = IntStream.range(0, 256).mapToObj(i -> "fixture:option_" + i).toList();
        var incomplete = new NormalizedRecipe.Requirement(0, 1, "tag", List.of(), List.of("fixture:wide"),
                wide, false, "Expansion exceeds the per-ingredient bound");
        var budget = new RetainedIngredientBudget(5, 5_100);

        for (int i = 0; i < 4_000; i++) {
            var retained = budget.retain(incomplete, true);
            assertFalse(retained.supported());
            assertTrue(retained.alternatives().isEmpty());
            assertEquals(List.of("fixture:wide"), retained.sourceTags());
        }
        var diamond = exact(0, "minecraft:diamond", 1);
        for (int i = 0; i < 3; i++) assertEquals(diamond, budget.retain(diamond, true));
        var stick = exact(0, "minecraft:stick", 1);
        for (int i = 0; i < 2; i++) assertEquals(stick, budget.retain(stick, true));
        assertEquals(5, budget.alternativesUsed());
        assertEquals(4_010, budget.identitiesUsed());
    }

    @Test
    void unsupportedWholeRecipeCannotSpendAlternativesOnOtherwiseSupportedInput() {
        var budget = new RetainedIngredientBudget(1, 10);
        var apparentInput = choice(0, 1, "fixture:first", "fixture:second");
        var retained = budget.retain(apparentInput, false);

        assertFalse(retained.supported());
        assertTrue(retained.alternatives().isEmpty());
        assertEquals(apparentInput.sourceTags(), retained.sourceTags());
        assertEquals(0, budget.alternativesUsed());
        assertEquals(exact(0, "fixture:later", 1), budget.retain(exact(0, "fixture:later", 1), true));
        assertEquals(1, budget.alternativesUsed());
    }

    @Test
    void identityRejectionDoesNotPartiallySpendAlternativeCapacity() {
        var budget = new RetainedIngredientBudget(5, 3);
        var tooWide = budget.retain(choice(0, 1, "fixture:a", "fixture:b", "fixture:c"), true);

        assertFalse(tooWide.supported());
        assertTrue(tooWide.alternatives().isEmpty());
        assertEquals(0, budget.alternativesUsed());
        assertEquals(1, budget.identitiesUsed());
        assertTrue(budget.retain(exact(1, "fixture:later", 1), true).supported());
        assertEquals(1, budget.alternativesUsed());
        assertEquals(3, budget.identitiesUsed());

        var exhausted = budget.retain(exact(2, "fixture:unknown", 1), true);
        assertFalse(exhausted.supported());
        assertTrue(exhausted.sourceItems().isEmpty());
        assertTrue(exhausted.alternatives().isEmpty());
        assertEquals(1, budget.alternativesUsed());
        assertEquals(3, budget.identitiesUsed());
    }

    @Test
    void rejectingAnAlternativeSetNeverTurnsItsTruncatedPrefixIntoKnownRequirement() {
        var budget = new RetainedIngredientBudget(2, 10);
        assertTrue(budget.retain(exact(0, "fixture:owned", 1), true).supported());
        var twoChoices = budget.retain(choice(1, 1, "fixture:a", "fixture:b"), true);

        assertFalse(twoChoices.supported());
        assertFalse(twoChoices.alternativesComplete());
        assertTrue(twoChoices.alternatives().isEmpty());
        assertEquals(List.of("fixture:materials"), twoChoices.sourceTags());
        assertEquals(1, budget.alternativesUsed());
        assertTrue(budget.retain(exact(2, "fixture:last", 1), true).supported());
        assertEquals(2, budget.alternativesUsed());
    }

    @Test
    void cheapKnownRecipesPrecedeWideAndOpaqueRecipesWithoutNamespacePreference() {
        var cheapModded = new RecipeSelection(0, 5, "zzz_mod:tool");
        var cheapVanilla = new RecipeSelection(0, 5, "minecraft:tool");
        var wideEarlier = new RecipeSelection(0, 256, "aaa_mod:wide");
        var incomplete = new RecipeSelection(1, 0, "aaa_mod:incomplete");
        var opaque = new RecipeSelection(2, 0, "aaa_mod:opaque");
        var choices = new ArrayList<>(List.of(opaque, wideEarlier, incomplete, cheapModded, cheapVanilla));

        Collections.sort(choices);
        assertEquals(List.of(cheapVanilla, cheapModded, wideEarlier, incomplete, opaque), choices);
        Collections.reverse(choices);
        Collections.sort(choices);
        assertEquals(List.of(cheapVanilla, cheapModded, wideEarlier, incomplete, opaque), choices);
    }
}
