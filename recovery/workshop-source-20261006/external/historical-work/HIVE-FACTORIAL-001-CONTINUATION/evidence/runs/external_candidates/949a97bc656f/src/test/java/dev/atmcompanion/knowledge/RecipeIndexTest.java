package dev.atmcompanion.knowledge;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;
import static dev.atmcompanion.knowledge.RecipeFixtures.*;

class RecipeIndexTest {
    @Test
    void outputLookupFindsAllRoutesInDeterministicRecipeIdOrder() {
        var first = recipe("fixture:a", "fixture:target", 1, exact(0, "fixture:iron", 1));
        var second = recipe("fixture:z", "fixture:target", 2, exact(0, "fixture:copper", 1));
        var unrelated = recipe("fixture:other", "fixture:other_output", 1, exact(0, "fixture:iron", 1));
        var index = index(second, unrelated, first);

        assertEquals(List.of(first, second), index.recipesFor("fixture:target"));
        assertEquals(List.of("fixture:a", "fixture:other", "fixture:z"), new ArrayList<>(index.recipesById().keySet()));
        assertEquals(2, index.outputRecipeCounts().get("fixture:target"));
        assertFalse(index.recipesForTruncated("fixture:target"));
        assertTrue(index.recipesFor("fixture:unknown").isEmpty());
        assertEquals(7, index.generation());
    }

    @Test
    void routeLimitsAreExplicitAndDoNotSilentlyClaimCompletePerOutputCoverage() {
        var recipes = IntStream.range(0, RecipeIndex.MAX_ROUTES_PER_OUTPUT + 5)
                .mapToObj(i -> recipe("fixture:route_" + String.format(java.util.Locale.ROOT, "%03d", i), "fixture:target", 1,
                        exact(0, "fixture:material", 1))).toList();
        var shuffled = new ArrayList<>(recipes);
        Collections.reverse(shuffled);
        var index = index(shuffled, false);

        assertEquals(RecipeIndex.MAX_ROUTES_PER_OUTPUT, index.recipesFor("fixture:target").size());
        assertTrue(index.recipesForTruncated("fixture:target"));
        assertEquals(recipes.size(), index.outputRecipeCounts().get("fixture:target"));
        assertEquals(recipes.subList(0, RecipeIndex.MAX_ROUTES_PER_OUTPUT), index.recipesFor("fixture:target"));
        assertEquals(recipes.size(), index.recipesById().size());
    }

    @Test
    void unsupportedEarlierPreviewsCannotDisplaceKnownMaterialRouteFromOutputLimit() {
        var recipes = new ArrayList<>(IntStream.range(0, RecipeIndex.MAX_ROUTES_PER_OUTPUT + 5)
                .mapToObj(i -> unsupported("a_preview:route_" + i, "fixture:target")).toList());
        var known = recipe("z_known:route", "fixture:target", 1, exact(0, "fixture:material", 1));
        recipes.add(known);
        Collections.reverse(recipes);

        var index = index(recipes, false);

        assertEquals(known, index.recipesFor("fixture:target").getFirst(),
                "An earlier preview must not hide the only actual material route");
        assertTrue(index.recipesForTruncated("fixture:target"));
        assertEquals(RecipeIndex.MAX_ROUTES_PER_OUTPUT, index.recipesFor("fixture:target").size());
        assertEquals(recipes.size(), index.outputRecipeCounts().get("fixture:target"));
    }

    @Test
    void partialBuildAndUnknownOutputsCannotBecomeACompleteIndex() {
        var normal = recipe("fixture:known", "fixture:target", 1, exact(0, "fixture:material", 1));
        assertFalse(index(List.of(normal), true).complete());
        var dynamic = new NormalizedRecipe("fixture:dynamic", "fixture:type", "fixture:serializer", null,
                List.of(), "dynamic", false, List.of("No fixed output preview"));
        var index = index(normal, dynamic);
        assertFalse(index.complete());
        assertEquals(1, index.stats().unknownOutputs());
        assertEquals(dynamic, index.recipesById().get("fixture:dynamic"));
        assertFalse(index.recipesByOutput().containsValue(List.of(dynamic)));
    }

    @Test
    void omittedInspectedRecipeCannotBeReportedAsCompleteCoverage() {
        var index = new RecipeIndex(1, 1, "2026-09-22T00:00:00Z", List.of(),
                new RecipeIndex.Stats(1, 1, 0, 0, 0, false, 0));

        assertFalse(index.complete(), "An inspected but absent normalized recipe leaves output coverage unknown");
    }

    @Test
    void nonfixedPreviewCannotBeMadeCompleteByOptimisticStatistics() {
        var preview = new NormalizedRecipe("fixture:preview", "fixture:custom", "fixture:custom",
                new NormalizedRecipe.Output("fixture:target", 1, false, false), List.of(), "unsupported", false, List.of("Preview only"));
        var index = new RecipeIndex(1, 1, "2026-09-22T00:00:00Z", List.of(preview),
                new RecipeIndex.Stats(1, 1, 1, 0, 1, false, 0));

        assertFalse(index.complete());
    }

    @Test
    void globalAlternativeBoundPreventsManyIndividuallyLegalRecipesFromEscapingMemoryLimits() {
        var alternatives = IntStream.range(0, NormalizedRecipe.MAX_ALTERNATIVES).mapToObj(i -> "fixture:item_" + i).toArray(String[]::new);
        var requirement = choice(0, 1, alternatives);
        var recipes = IntStream.range(0, RecipeIndex.MAX_TOTAL_ALTERNATIVES / alternatives.length + 1)
                .mapToObj(i -> recipe("fixture:recipe_" + i, "fixture:target", 1, requirement)).toList();

        assertThrows(IllegalArgumentException.class, () -> index(recipes, false));
    }

    @Test
    void completeStaticCoverageDoesNotClaimUnsupportedRecipeSemantics() {
        var machine = unsupported("fixture:machine", "fixture:target");
        var index = index(machine);
        assertTrue(index.complete(), "Complete means complete static output coverage only");
        assertFalse(index.recipesFor("fixture:target").getFirst().dependencySupported());
        assertEquals(1, index.stats().unsupportedRecipes());
    }

    @Test
    void mapsRoutesAndSourceListsAreImmutableCopies() {
        var recipes = new ArrayList<>(List.of(recipe("fixture:r", "fixture:target", 1, exact(0, "fixture:material", 1))));
        var index = index(recipes, false);
        recipes.clear();
        assertEquals(1, index.recipesById().size());
        assertThrows(UnsupportedOperationException.class, () -> index.recipesById().clear());
        assertThrows(UnsupportedOperationException.class, () -> index.recipesByOutput().clear());
        assertThrows(UnsupportedOperationException.class, () -> index.outputRecipeCounts().clear());
        assertThrows(UnsupportedOperationException.class, () -> index.recipesFor("fixture:target").clear());
    }

    @Test
    void duplicateIdsAndInconsistentMetadataAreRejected() {
        var recipe = recipe("fixture:r", "fixture:target", 1, exact(0, "fixture:material", 1));
        assertThrows(IllegalArgumentException.class, () -> index(recipe, recipe));
        assertThrows(IllegalArgumentException.class, () -> new RecipeIndex(1, 1, "2026-09-22T00:00:00Z", List.of(recipe),
                new RecipeIndex.Stats(0, 0, 0, 0, 0, false, 0)));
        assertThrows(IllegalArgumentException.class, () -> new RecipeIndex.Stats(5, 3, 3, 0, 0, false, 0));
        assertThrows(IllegalArgumentException.class, () -> new RecipeIndex.Stats(1, 1, 1, 2, 0, false, 0));
        assertThrows(IllegalArgumentException.class, () -> new RecipeIndex(3, 1, "2026-09-22T00:00:00Z", List.of(),
                new RecipeIndex.Stats(0, 0, 0, 0, 0, false, 0)));
    }
}
