package dev.atmcompanion.knowledge;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;

class IngredientAllocationTest {
    @Test
    void overlappingAlternativesNeedReallocationRatherThanGreedyConsumption() {
        // Position 0 permits oak or birch; position 1 permits only oak.
        assertTrue(IngredientAllocation.canSatisfy(List.of(List.of(0, 1), List.of(0)), Map.of(0, 1, 1, 1)));
    }

    @Test
    void onePhysicalItemCannotSatisfyTwoIngredientPositions() {
        assertFalse(IngredientAllocation.canSatisfy(List.of(List.of(0), List.of(0)), Map.of(0, 1)));
        assertTrue(IngredientAllocation.canSatisfy(List.of(List.of(0), List.of(0)), Map.of(0, 2)));
    }

    @Test
    void missingEmptyAndUnknownSlotsAreHandledWithoutInventingInventory() {
        assertTrue(IngredientAllocation.canSatisfy(List.of(), Map.of()));
        assertFalse(IngredientAllocation.canSatisfy(List.of(List.of()), Map.of(0, 64)));
        assertFalse(IngredientAllocation.canSatisfy(List.of(List.of(0)), Map.of()));
        assertFalse(IngredientAllocation.canSatisfy(List.of(List.of(0)), Map.of(0, 0)));
        assertFalse(IngredientAllocation.canSatisfy(List.of(List.of(1)), Map.of(0, 64)));
    }

    @Test
    void inputBoundsAndNegativeCountsAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(
                IntStream.range(0, 10).mapToObj(i -> List.of(0)).toList(), Map.of(0, 64)));
        var tooManyCounts = new LinkedHashMap<Integer, Integer>();
        IntStream.range(0, 37).forEach(slot -> tooManyCounts.put(slot, 1));
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(), tooManyCounts));
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(
                List.of(IntStream.range(0, 37).boxed().toList()), Map.of()));
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(), Map.of(0, -1)));
    }

    @Test
    void allocationDoesNotMutateCallerInventory() {
        var counts = new LinkedHashMap<>(Map.of(0, 3, 1, 2));
        var original = Map.copyOf(counts);
        assertTrue(IngredientAllocation.canSatisfy(List.of(List.of(0, 1), List.of(0)), counts));
        assertEquals(original, counts);
    }

    @Test
    void allThreeSlotThreeRequirementCasesMatchAnIndependentExhaustiveOracle() {
        // 8^3 alternative sets x 3^3 stack capacities = 13,824 complete cases.
        // Oracle consumes physical counts by exhaustive search, independently of production matching.
        for (int mask0 = 0; mask0 < 8; mask0++) {
            for (int mask1 = 0; mask1 < 8; mask1++) {
                for (int mask2 = 0; mask2 < 8; mask2++) {
                    var requirements = List.of(slots(mask0), slots(mask1), slots(mask2));
                    for (int count0 = 0; count0 <= 2; count0++) {
                        for (int count1 = 0; count1 <= 2; count1++) {
                            for (int count2 = 0; count2 <= 2; count2++) {
                                int[] counts = {count0, count1, count2};
                                boolean expected = exhaustive(requirements, 0, counts.clone());
                                boolean actual = IngredientAllocation.canSatisfy(requirements,
                                        Map.of(0, count0, 1, count1, 2, count2));
                                assertEquals(expected, actual, () -> "requirements=" + requirements + ", counts=" + java.util.Arrays.toString(counts));
                            }
                        }
                    }
                }
            }
        }
    }

    private static List<Integer> slots(int mask) {
        var slots = new ArrayList<Integer>();
        for (int slot = 0; slot < 3; slot++) if ((mask & (1 << slot)) != 0) slots.add(slot);
        return List.copyOf(slots);
    }

    private static boolean exhaustive(List<List<Integer>> requirements, int position, int[] remaining) {
        if (position == requirements.size()) return true;
        for (int slot : requirements.get(position)) {
            if (remaining[slot] == 0) continue;
            remaining[slot]--;
            boolean matched = exhaustive(requirements, position + 1, remaining);
            remaining[slot]++;
            if (matched) return true;
        }
        return false;
    }
}
