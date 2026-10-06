package dev.atmcompanion.planning;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.knowledge.RecipeFixtures;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static dev.atmcompanion.knowledge.RecipeFixtures.*;
import static org.junit.jupiter.api.Assertions.*;

class DeterministicPlannerTest {
    private final DeterministicPlanner planner = new DeterministicPlanner();

    @Test
    void sharedInventoryAcrossSiblingBranchesCountsTenIronOnlyOnce() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, exact(0, "fixture:a", 1), exact(1, "fixture:b", 1)),
                recipe("fixture:a", "fixture:a", 1, exact(0, "fixture:iron", 6)),
                recipe("fixture:b", "fixture:b", 1, exact(0, "fixture:iron", 6)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:iron", 10L));

        assertEquals("blocked", plan.status());
        assertEquals(Map.of("fixture:iron", 10L), resources(plan.ownedRequirements()));
        assertEquals(Map.of("fixture:iron", 2L), resources(plan.missingRequirements()));
        assertEquals("obtain", plan.nextAction().kind());
        assertEquals(2, plan.nextAction().quantity());
    }

    @Test
    void constrainedExactRequirementDoesNotLoseItsItemToAnOverlappingTag() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1,
                choice(0, 1, "fixture:oak", "fixture:birch"), exact(1, "fixture:oak", 1)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:oak", 1L, "fixture:birch", 1L));

        assertEquals("materials_ready", plan.status());
        assertTrue(plan.missingRequirements().isEmpty());
        assertEquals(Map.of("fixture:oak", 1L, "fixture:birch", 1L), resources(plan.ownedRequirements()));
    }

    @Test
    void groupedTagDemandCanUseMultipleDifferentValidAlternatives() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, choice(0, 3, "fixture:oak", "fixture:birch")));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:oak", 2L, "fixture:birch", 1L));

        assertEquals("materials_ready", plan.status());
        assertEquals(3, plan.ownedRequirements().stream().mapToLong(PlanResult.Resource::quantity).sum());
        assertTrue(plan.missingRequirements().isEmpty());
    }

    @Test
    void groupedTagDemandCanManufactureDifferentAlternativesFromDifferentOwnedInputs() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, choice(0, 2, "fixture:a", "fixture:b")),
                recipe("fixture:make_a", "fixture:a", 1, exact(0, "fixture:x", 1)),
                recipe("fixture:make_b", "fixture:b", 1, exact(0, "fixture:y", 1)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:x", 1L, "fixture:y", 1L));

        assertEquals("materials_ready", plan.status(),
                "Neither two A nor two B is feasible; one of each must satisfy the shared OR requirement");
        assertTrue(plan.missingRequirements().isEmpty());
        assertTrue(plan.unsupportedSteps().isEmpty());
        assertEquals(Map.of("fixture:x", 1L, "fixture:y", 1L), resources(plan.ownedRequirements()));
        assertEquals(1, plan.selectedPath().stream().filter(step -> step.recipeId().equals("fixture:make_a"))
                .mapToLong(step -> step.crafts()).sum());
        assertEquals(1, plan.selectedPath().stream().filter(step -> step.recipeId().equals("fixture:make_b"))
                .mapToLong(step -> step.crafts()).sum());
        assertEquals("fixture:goal", plan.selectedPath().getLast().recipeId());
        assertEquals(Map.of("fixture:a", 1L, "fixture:b", 1L), plan.selectedPath().getLast().ingredients().stream()
                .collect(java.util.stream.Collectors.toMap(PlanResult.AllocatedIngredient::item, PlanResult.AllocatedIngredient::quantity, Long::sum)),
                "Execution inputs must name the actual selected tag members, not upstream raw resources");
        assertTrue(plan.selectedPath().getLast().ingredients().stream().allMatch(input -> input.position() == 0));
    }

    @Test
    void broadEarlierRootRouteCannotStarveALaterReadyRouteOfTheGlobalNodeBudget() {
        String[] alternatives = {"fixture:i0", "fixture:i1", "fixture:i2", "fixture:i3", "fixture:i4", "fixture:i5"};
        var recipes = new ArrayList<NormalizedRecipe>();
        recipes.add(recipe("fixture:a_expensive", "fixture:goal", 1,
                choice(0, 1, alternatives), choice(1, 1, alternatives), choice(2, 1, alternatives),
                choice(3, 1, alternatives), choice(4, 1, alternatives), choice(5, 1, alternatives)));
        for (int i = 0; i < alternatives.length; i++) {
            recipes.add(recipe("fixture:make_i" + i, alternatives[i], 1, exact(0, "fixture:raw" + i, 1)));
        }
        recipes.add(recipe("fixture:z_ready", "fixture:goal", 1, exact(0, "fixture:owned_token", 1)));

        var plan = planner.plan(index(recipes, false), "fixture:goal", 1, Map.of("fixture:owned_token", 1L));

        assertEquals("materials_ready", plan.status(), "A ready root route within the route cap must receive search capacity");
        assertEquals(List.of("fixture:z_ready"), plan.selectedPath().stream().map(step -> step.recipeId()).toList());
        assertEquals(Map.of("fixture:owned_token", 1L), resources(plan.ownedRequirements()));
        assertTrue(plan.missingRequirements().isEmpty());
        assertTrue(plan.unsupportedSteps().isEmpty());
        assertTrue(plan.metrics().expandedNodes() <= DeterministicPlanner.Limits.defaults().nodes(),
                "Root fairness must not grant a separate unbounded budget to every route");
    }

    @Test
    void outputBatchingUsesCeilingAndReusesHypotheticalSurplusAcrossSiblings() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, exact(0, "fixture:a", 3), exact(1, "fixture:b", 1)),
                recipe("fixture:a", "fixture:a", 2, exact(0, "fixture:iron", 3)),
                recipe("fixture:b", "fixture:b", 1, exact(0, "fixture:a", 1)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:iron", 6L));

        assertEquals("materials_ready", plan.status());
        assertEquals(Map.of("fixture:iron", 6L), resources(plan.ownedRequirements()));
        assertTrue(plan.missingRequirements().isEmpty());
        var aSteps = plan.selectedPath().stream().filter(step -> step.output().equals("fixture:a")).toList();
        assertEquals(1, aSteps.size());
        assertEquals(2, aSteps.getFirst().crafts());
        assertEquals(4, aSteps.getFirst().outputQuantity());
        assertEquals("fixture:a", plan.nextAction().recipeId());
    }

    @Test
    void futureBatchSurplusNeverAppearsAsCurrentlyOwnedEvenWithMissingRawInputs() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, exact(0, "fixture:a", 3), exact(1, "fixture:b", 1)),
                recipe("fixture:a", "fixture:a", 2, exact(0, "fixture:iron", 3)),
                recipe("fixture:b", "fixture:b", 1, exact(0, "fixture:a", 1)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of());

        assertEquals("blocked", plan.status());
        assertTrue(plan.ownedRequirements().isEmpty());
        assertEquals(Map.of("fixture:iron", 6L), resources(plan.missingRequirements()));
        assertTrue(plan.limitations().stream().anyMatch(text -> text.contains("hypothetical")));
    }

    @Test
    void alreadyOwnedGoalDoesNotInventRequiredCraftsOrInspectUnneededRecipes() {
        var plan = planner.plan(index(), "fixture:goal", 3, Map.of("fixture:goal", 5L));

        assertEquals("already_owned", plan.status());
        assertEquals(Map.of("fixture:goal", 3L), resources(plan.ownedRequirements()));
        assertTrue(plan.selectedPath().isEmpty());
        assertTrue(plan.missingRequirements().isEmpty());
        assertEquals("complete", plan.nextAction().kind());
        assertEquals(0, plan.metrics().expandedNodes());
    }

    @Test
    void partialOwnershipReducesProductionDemandBeforeOutputBatchRounding() {
        var plan = planner.plan(index(recipe("fixture:r", "fixture:goal", 4, exact(0, "fixture:wood", 2))),
                "fixture:goal", 3, Map.of("fixture:goal", 1L, "fixture:wood", 2L));

        assertEquals("materials_ready", plan.status());
        assertEquals(1, plan.selectedPath().getFirst().crafts());
        assertEquals(4, plan.selectedPath().getFirst().outputQuantity());
        assertEquals(Map.of("fixture:goal", 1L, "fixture:wood", 2L), resources(plan.ownedRequirements()));
    }

    @Test
    void routeWithObservedInputsWinsOverRouteWithMissingInputs() {
        var index = index(recipe("fixture:iron_route", "fixture:goal", 1, exact(0, "fixture:iron", 5)),
                recipe("fixture:copper_route", "fixture:goal", 1, exact(0, "fixture:copper", 2)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:copper", 2L));

        assertEquals("materials_ready", plan.status());
        assertEquals("fixture:copper_route", plan.selectedPath().getLast().recipeId());
        assertFalse(plan.alternativePaths().isEmpty());
    }

    @Test
    void cyclesTerminateWithoutPretendingHypotheticalOutputsExist() {
        var index = index(recipe("fixture:a", "fixture:a", 1, exact(0, "fixture:b", 1)),
                recipe("fixture:b", "fixture:b", 1, exact(0, "fixture:c", 1)),
                recipe("fixture:c", "fixture:c", 1, exact(0, "fixture:a", 1)));
        var plan = planner.plan(index, "fixture:a", 1, Map.of());

        assertEquals("unsupported", plan.status());
        assertTrue(plan.unsupportedSteps().stream().anyMatch(issue -> issue.kind().equals("cycle")));
        assertTrue(plan.ownedRequirements().isEmpty());
        assertEquals("inspect", plan.nextAction().kind());
        assertTrue(plan.metrics().expandedNodes() <= DeterministicPlanner.Limits.defaults().nodes());
    }

    @Test
    void acyclicAlternativeCanEscapeACyclicRecipeRoute() {
        var index = index(recipe("fixture:cycle_a", "fixture:a", 1, exact(0, "fixture:b", 1)),
                recipe("fixture:cycle_b", "fixture:b", 1, exact(0, "fixture:a", 1)),
                recipe("fixture:exit", "fixture:a", 1, exact(0, "fixture:iron", 2)));
        var plan = planner.plan(index, "fixture:a", 1, Map.of("fixture:iron", 2L));

        assertEquals("materials_ready", plan.status());
        assertTrue(plan.unsupportedSteps().isEmpty());
        assertEquals("fixture:exit", plan.selectedPath().getLast().recipeId());
    }

    @Test
    void unsupportedMachineNeverBecomesARecipePreparationAction() {
        var plan = planner.plan(index(unsupported("fixture:machine", "fixture:goal")), "fixture:goal", 1, Map.of());

        assertEquals("unsupported", plan.status());
        assertEquals("inspect", plan.nextAction().kind());
        assertTrue(plan.unsupportedSteps().stream().anyMatch(issue -> issue.kind().equals("unsupported_recipe")));
        assertTrue(plan.ownedRequirements().isEmpty());
    }

    @Test
    void unresolvedOpaquePrerequisiteIsInspectedBeforeRecommendingMaterialSpending() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1,
                exact(0, "fixture:machine_part", 1), exact(1, "fixture:diamond", 4)),
                unsupported("fixture:machine", "fixture:machine_part"));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of());

        assertEquals("unsupported", plan.status());
        assertEquals(Map.of("fixture:diamond", 4L), resources(plan.missingRequirements()));
        assertEquals("inspect", plan.nextAction().kind(), "Unknown prerequisites should be resolved before suggesting further commitment to this route");
        assertEquals("fixture:machine_part", plan.nextAction().item());
    }

    @Test
    void missingRouteInPartialIndexRetainsExplicitKnowledgeUncertainty() {
        var plan = planner.plan(RecipeFixtures.index(List.of(), true), "fixture:goal", 1, Map.of());

        assertNotEquals("materials_ready", plan.status());
        assertFalse(plan.metrics().indexComplete());
        assertEquals(Map.of("fixture:goal", 1L), resources(plan.missingRequirements()));
        assertTrue(plan.limitations().stream().anyMatch(text -> text.contains("does not prove no route exists")));
    }

    @Test
    void nodeAndDepthLimitsAreReportedAndBoundExpansion() {
        var index = index(recipe("fixture:a", "fixture:a", 1, exact(0, "fixture:b", 1)),
                recipe("fixture:b", "fixture:b", 1, exact(0, "fixture:c", 1)));
        var nodeBounded = new DeterministicPlanner(new DeterministicPlanner.Limits(10, 1, 6, 6, 6))
                .plan(index, "fixture:a", 1, Map.of());
        assertEquals("search_limited", nodeBounded.status());
        assertTrue(nodeBounded.metrics().searchTruncated());
        assertTrue(nodeBounded.metrics().expandedNodes() <= 1);

        var depthBounded = new DeterministicPlanner(new DeterministicPlanner.Limits(1, 768, 6, 6, 6))
                .plan(index, "fixture:a", 1, Map.of());
        assertEquals("search_limited", depthBounded.status());
        assertTrue(depthBounded.metrics().searchTruncated());
        assertTrue(depthBounded.metrics().depth() <= 2);
    }

    @Test
    void recipeAndAlternativeSearchCapsAreNeverSilent() {
        var index = index(recipe("fixture:a", "fixture:goal", 1, choice(0, 1, "fixture:iron", "fixture:copper")),
                recipe("fixture:b", "fixture:goal", 1, exact(0, "fixture:wood", 1)));
        var plan = new DeterministicPlanner(new DeterministicPlanner.Limits(10, 768, 1, 1, 6))
                .plan(index, "fixture:goal", 1, Map.of());

        assertTrue(plan.metrics().searchTruncated());
        assertTrue(plan.limitations().stream().anyMatch(text -> text.contains("Search limit")));
    }

    @Test
    void hugeIngredientMultiplicationCannotOverflowIntoReadyOrNegativeResources() {
        var index = index(recipe("fixture:huge", "fixture:goal", 1, exact(0, "fixture:iron", Integer.MAX_VALUE)));
        var plan = planner.plan(index, "fixture:goal", DeterministicPlanner.MAX_QUANTITY, Map.of());

        assertEquals("search_limited", plan.status());
        assertTrue(plan.unsupportedSteps().stream().allMatch(issue -> issue.quantity() > 0));
        assertTrue(plan.ownedRequirements().stream().allMatch(resource -> resource.quantity() > 0));
        assertTrue(plan.missingRequirements().stream().allMatch(resource -> resource.quantity() > 0));
    }

    @Test
    void malformedGoalCountsAndInventoryFactsAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> planner.plan(index(), "goal", 1, Map.of()));
        assertThrows(IllegalArgumentException.class, () -> planner.plan(index(), "fixture:goal", 0, Map.of()));
        assertThrows(IllegalArgumentException.class, () -> planner.plan(index(), "fixture:goal", Long.MAX_VALUE, Map.of()));
        assertThrows(IllegalArgumentException.class, () -> planner.plan(index(), "fixture:goal", 1, Map.of("fixture:iron", -1L)));
        assertThrows(IllegalArgumentException.class, () -> new DeterministicPlanner.Limits(0, 1, 1, 1, 1));
    }

    @Test
    void planDoesNotMutateInputAndDeterministicFactsIgnoreInsertionOrder() {
        var a = recipe("fixture:a", "fixture:goal", 1, choice(0, 1, "fixture:iron", "fixture:copper"));
        var b = recipe("fixture:b", "fixture:goal", 1, exact(0, "fixture:wood", 1));
        var inventory = new LinkedHashMap<String, Long>();
        inventory.put("fixture:iron", 2L);
        inventory.put("fixture:copper", 2L);
        var before = Map.copyOf(inventory);
        var first = planner.plan(index(a, b), "fixture:goal", 1, inventory);
        var second = planner.plan(index(b, a), "fixture:goal", 1, Map.of("fixture:copper", 2L, "fixture:iron", 2L));

        assertEquals(before, inventory);
        assertEquals(first.status(), second.status());
        assertEquals(first.selectedPath(), second.selectedPath());
        assertEquals(first.ownedRequirements(), second.ownedRequirements());
        assertEquals(first.missingRequirements(), second.missingRequirements());
        assertEquals(first.nextAction(), second.nextAction());
    }

    @Test
    void prerequisiteRecipeIsSuggestedBeforeItsDependentGoalRecipe() {
        var index = index(recipe("fixture:goal", "fixture:goal", 1, exact(0, "fixture:part", 1)),
                recipe("fixture:part", "fixture:part", 1, exact(0, "fixture:iron", 2)));
        var plan = planner.plan(index, "fixture:goal", 1, Map.of("fixture:iron", 2L));

        assertEquals("prepare_recipe", plan.nextAction().kind());
        assertEquals("fixture:part", plan.nextAction().recipeId());
        assertEquals(List.of("fixture:part", "fixture:goal"), plan.selectedPath().stream().map(PlanResult.Step::recipeId).toList());
        assertTrue(plan.limitations().stream().anyMatch(text -> text.contains("byproducts are not credited")));
        assertTrue(plan.limitations().stream().anyMatch(text -> text.contains("execution are not verified")));
    }

    @Test
    void threeOverlappingTagRequirementsMatchAnIndependentAllocationOracle() {
        var thorough = new DeterministicPlanner(new DeterministicPlanner.Limits(10, 4096, 32, 32, 16));
        // All 7^3 nonempty alternative sets, each at eight binary ownership patterns: 2,744 cases.
        for (int a = 1; a < 8; a++) for (int b = 1; b < 8; b++) for (int c = 1; c < 8; c++) {
            var options = List.of(items(a), items(b), items(c));
            var index = index(recipe("fixture:goal", "fixture:goal", 1,
                    choice(0, 1, options.get(0).toArray(String[]::new)),
                    choice(1, 1, options.get(1).toArray(String[]::new)),
                    choice(2, 1, options.get(2).toArray(String[]::new))));
            for (int ownership = 0; ownership < 8; ownership++) {
                int[] counts = {(ownership & 1) != 0 ? 1 : 0, (ownership & 2) != 0 ? 1 : 0, (ownership & 4) != 0 ? 1 : 0};
                var inventory = Map.of("fixture:a", (long) counts[0], "fixture:b", (long) counts[1], "fixture:c", (long) counts[2]);
                int expectedMissing = minimumMissing(options, 0, counts.clone());
                var plan = thorough.plan(index, "fixture:goal", 1, inventory);
                long actualMissing = plan.missingRequirements().stream().mapToLong(PlanResult.Resource::quantity).sum();
                assertEquals(expectedMissing, actualMissing, () -> "options=" + options + ", owned=" + inventory + ", plan=" + plan);
                assertTrue(plan.unsupportedSteps().isEmpty());
            }
        }
    }

    private static Map<String, Long> resources(List<PlanResult.Resource> resources) {
        var result = new LinkedHashMap<String, Long>();
        for (var resource : resources) assertNull(result.put(resource.item(), resource.quantity()), "Duplicate resource entry");
        return result;
    }

    private static List<String> items(int mask) {
        var items = new ArrayList<String>();
        for (int i = 0; i < 3; i++) if ((mask & (1 << i)) != 0) items.add("fixture:" + (char) ('a' + i));
        return items;
    }

    private static int minimumMissing(List<List<String>> options, int position, int[] inventory) {
        if (position == options.size()) return 0;
        int best = 1 + minimumMissing(options, position + 1, inventory);
        for (String item : options.get(position)) {
            int slot = item.charAt(item.length() - 1) - 'a';
            if (inventory[slot] == 0) continue;
            inventory[slot]--;
            best = Math.min(best, minimumMissing(options, position + 1, inventory));
            inventory[slot]++;
        }
        return best;
    }
}
