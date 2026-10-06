package dev.atmcompanion.knowledge;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;
import static dev.atmcompanion.knowledge.RecipeFixtures.*;

class NormalizedRecipeTest {
    @Test
    void legacyMaterialRecipesDoNotInventExecutionMetadata() {
        var recipe = recipe("fixture:r", "fixture:output", 1, exact(0, "fixture:input", 1));
        assertTrue(recipe.dependencySupported());
        assertEquals(NormalizedRecipe.ExecutionRequirement.unknown(), recipe.execution());
        assertFalse(recipe.execution().fits2x2());
        assertFalse(recipe.execution().fits3x3());
    }

    @Test
    void executionMetadataPreservesShapeAndTimingAndRejectsContradictoryKinds() {
        var column = new NormalizedRecipe.ExecutionRequirement("crafting", false, true, 1, 3, 0);
        assertEquals(1, column.width());
        assertEquals(3, column.height());
        assertFalse(column.fits2x2());
        assertEquals(321, new NormalizedRecipe.ExecutionRequirement("smelting", false, false, 0, 0, 321).cookingTicks());
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe.ExecutionRequirement("crafting", true, false, 2, 2, 0));
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe.ExecutionRequirement("smelting", true, true, 2, 2, 200));
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe.ExecutionRequirement("unknown", false, false, 0, 0, 200));
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe.ExecutionRequirement("crafting", false, true, 0, 3, 0));
    }

    @Test
    void sourcesAndResolvedAlternativesRemainSeparateImmutableCanonicalSets() {
        var alternatives = new ArrayList<>(List.of("fixture:zinc", "fixture:copper", "fixture:zinc"));
        var requirement = new NormalizedRecipe.Requirement(2, 3, "alternatives",
                List.of("fixture:zinc"), List.of("c:ingots/zinc", "c:ingots/copper", "c:ingots/zinc"), alternatives, true, "OR alternatives");
        alternatives.clear();

        assertEquals(List.of("fixture:copper", "fixture:zinc"), requirement.alternatives());
        assertEquals(List.of("fixture:zinc"), requirement.sourceItems());
        assertEquals(List.of("c:ingots/copper", "c:ingots/zinc"), requirement.sourceTags());
        assertEquals(3, requirement.count());
        assertTrue(requirement.supported());
        assertThrows(UnsupportedOperationException.class, () -> requirement.alternatives().clear());
        assertThrows(UnsupportedOperationException.class, () -> requirement.sourceTags().clear());
    }

    @Test
    void customIncompleteAndEmptyTagRequirementsCannotBecomeSupportedDependencies() {
        var unsupported = List.of(
                new NormalizedRecipe.Requirement(0, 1, "custom", List.of(), List.of(), List.of("fixture:item"), true, "Custom component predicate"),
                new NormalizedRecipe.Requirement(0, 1, "tag", List.of(), List.of("fixture:empty"), List.of(), true, "Empty tag"),
                new NormalizedRecipe.Requirement(0, 1, "tag", List.of(), List.of("fixture:large"), List.of("fixture:item"), false, "Partial alternatives"));
        for (var requirement : unsupported) {
            assertFalse(requirement.supported());
            assertThrows(IllegalArgumentException.class, () -> recipe("fixture:bad", "fixture:output", 1, requirement));
        }
    }

    @Test
    void dynamicAndComponentOutputsRemainUnsupportedEvenWhenTheyHaveAPreview() {
        for (var output : List.of(new NormalizedRecipe.Output("fixture:output", 1, false, false),
                new NormalizedRecipe.Output("fixture:output", 1, true, true))) {
            assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe("fixture:recipe", "fixture:type", "fixture:serializer",
                    output, List.of(exact(0, "fixture:input", 1)), "custom", true, List.of()));
        }
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe("fixture:recipe", "fixture:type", "fixture:serializer",
                null, List.of(exact(0, "fixture:input", 1)), "custom", true, List.of()));
    }

    @Test
    void countsAndRequirementListsAreBounded() {
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe.Output("fixture:item", 0, true, false));
        assertThrows(IllegalArgumentException.class, () -> exact(0, "fixture:item", 0));
        assertThrows(IllegalArgumentException.class, () -> exact(-1, "fixture:item", 1));
        var tooManyAlternatives = IntStream.range(0, NormalizedRecipe.MAX_ALTERNATIVES + 1).mapToObj(i -> "fixture:item_" + i).toList();
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe.Requirement(0, 1, "tag", List.of(),
                List.of("fixture:huge"), tooManyAlternatives, true, "Too large"));
        var tooManyRequirements = IntStream.range(0, NormalizedRecipe.MAX_REQUIREMENTS + 1).mapToObj(i -> exact(i, "fixture:item", 1)).toList();
        assertThrows(IllegalArgumentException.class, () -> new NormalizedRecipe("fixture:recipe", "fixture:type", "fixture:serializer",
                new NormalizedRecipe.Output("fixture:output", 1, true, false), tooManyRequirements, "crafting", true, List.of()));
    }
}
