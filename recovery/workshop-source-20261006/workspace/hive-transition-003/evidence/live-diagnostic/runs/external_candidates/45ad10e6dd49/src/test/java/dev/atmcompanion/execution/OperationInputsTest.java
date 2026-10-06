package dev.atmcompanion.execution;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.planning.PlanResult;
import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import static dev.atmcompanion.knowledge.RecipeFixtures.*;
import static org.junit.jupiter.api.Assertions.*;

class OperationInputsTest {
    private static final String A = "fixture:a", B = "fixture:b", C = "fixture:c";

    @Test
    void oneOperationCanUseAnyActuallyAllocatedBatchMemberButNotAnUnselectedTagMember() {
        var recipe = recipe("fixture:r", "fixture:goal", 1, choice(0, 1, A, B, C));
        var step = step(recipe, 2, List.of(input(0, A, 1), input(0, B, 1)));

        var chosen = OperationInputs.select(recipe, step, Map.of(B, 1L));
        assertTrue(chosen.ready());
        assertEquals(List.of(new PlanResult.Resource(B, 1)), chosen.inputs());
        assertFalse(OperationInputs.select(recipe, step, Map.of(C, 1L)).ready(),
                "A valid runtime tag member is not necessarily part of this selected material path");
        assertFalse(OperationInputs.select(recipe, step, Map.of()).ready(), "Planned inputs cannot become observed ownership");
    }

    @Test
    void overlappingSlotsBacktrackWithoutDoubleCountingTheOnlyExactItem() {
        var recipe = recipe("fixture:r", "fixture:goal", 1, choice(0, 1, A, B), exact(1, A, 1));
        var step = step(recipe, 2, List.of(input(0, A, 1), input(0, B, 1), input(1, A, 2)));
        var result = OperationInputs.select(recipe, step, Map.of(A, 1L, B, 1L));

        assertTrue(result.ready());
        assertEquals(Map.of(A, 1L, B, 1L), counts(result.inputs()));
        assertFalse(OperationInputs.select(recipe, step, Map.of(A, 1L)).ready());
    }

    @Test
    void malformedOrIncompleteProvenanceCannotAuthorizeAnOperation() {
        var recipe = recipe("fixture:r", "fixture:goal", 1, exact(0, A, 1));
        assertFalse(OperationInputs.select(recipe, step(recipe, 2, List.of(input(0, A, 1))), Map.of(A, 9L)).ready());
        assertFalse(OperationInputs.select(recipe, step(recipe, 1, List.of(input(0, B, 1))), Map.of(B, 9L)).ready());
        assertFalse(OperationInputs.select(recipe, step(recipe, 1, List.of(input(9, A, 1))), Map.of(A, 9L)).ready());
        assertFalse(OperationInputs.select(recipe, new PlanResult.Step("fixture:other", "fixture:goal", 1, 1,
                "minecraft:crafting", 0, List.of(), List.of(input(0, A, 1))), Map.of(A, 9L)).ready());
        assertFalse(OperationInputs.select(recipe, new PlanResult.Step("fixture:r", "fixture:wrong", 1, 1,
                "minecraft:crafting", 0, List.of(), List.of(input(0, A, 1))), Map.of(A, 9L)).ready());
        assertFalse(OperationInputs.select(recipe, new PlanResult.Step("fixture:r", "fixture:goal", 1, 0,
                "minecraft:crafting", 0, List.of(), List.of()), Map.of(A, 9L)).ready());
    }

    @Test
    void oversizedSingleOperationRemainsExplicitlyUnresolved() {
        var recipe = recipe("fixture:r", "fixture:goal", 1, exact(0, A, 65));
        var result = OperationInputs.select(recipe, step(recipe, 1, List.of(input(0, A, 65))), Map.of(A, 65L));
        assertFalse(result.ready());
        assertTrue(result.truncated());
        assertFalse(result.detail().isBlank());
    }

    @Test
    void selectedInputSubsetsMatchAnIndependentFeasibilityOracle() {
        var recipe = recipe("fixture:r", "fixture:goal", 1,
                choice(0, 1, A, B, C), choice(1, 1, A, B, C), choice(2, 1, A, B, C));
        String[] items = {A, B, C};
        for (int first = 1; first < 8; first++) for (int second = 1; second < 8; second++) for (int third = 1; third < 8; third++) {
            int[] masks = {first, second, third};
            var allocated = new ArrayList<PlanResult.AllocatedIngredient>();
            for (int position = 0; position < masks.length; position++) {
                int left = 3;
                for (int item = 0; item < items.length; item++) if ((masks[position] & (1 << item)) != 0) {
                    int later = Integer.bitCount(masks[position] >>> (item + 1));
                    int quantity = later == 0 ? left : 1;
                    allocated.add(input(position, items[item], quantity));
                    left -= quantity;
                }
            }
            var step = step(recipe, 3, allocated);
            for (int held = 0; held < 8; held++) {
                int[] capacities = {held & 1, (held >>> 1) & 1, (held >>> 2) & 1};
                var result = OperationInputs.select(recipe, step, Map.of(A, (long) capacities[0], B, (long) capacities[1], C, (long) capacities[2]));
                boolean expected = feasible(masks, 0, capacities.clone());
                assertEquals(expected, result.ready(), "Selected masks " + first + "/" + second + "/" + third + ", inventory mask " + held);
                if (result.ready()) {
                    assertEquals(3, result.inputs().stream().mapToLong(PlanResult.Resource::quantity).sum());
                    for (var used : result.inputs()) assertTrue(used.quantity() <= 1, "One physical item was allocated to multiple positions");
                }
            }
        }
    }

    private static boolean feasible(int[] masks, int position, int[] available) {
        if (position == masks.length) return true;
        for (int item = 0; item < available.length; item++) if ((masks[position] & (1 << item)) != 0 && available[item] > 0) {
            available[item]--;
            boolean possible = feasible(masks, position + 1, available);
            available[item]++;
            if (possible) return true;
        }
        return false;
    }
    private static PlanResult.AllocatedIngredient input(int position, String item, long count) {
        return new PlanResult.AllocatedIngredient(position, item, count);
    }
    private static PlanResult.Step step(NormalizedRecipe recipe, long crafts, List<PlanResult.AllocatedIngredient> inputs) {
        return new PlanResult.Step(recipe.id(), recipe.output().item(), crafts * recipe.output().count(), crafts, recipe.type(), 0, List.of(), inputs);
    }
    private static Map<String, Long> counts(List<PlanResult.Resource> inputs) {
        return inputs.stream().collect(java.util.stream.Collectors.toMap(PlanResult.Resource::item, PlanResult.Resource::quantity, Long::sum));
    }
}
