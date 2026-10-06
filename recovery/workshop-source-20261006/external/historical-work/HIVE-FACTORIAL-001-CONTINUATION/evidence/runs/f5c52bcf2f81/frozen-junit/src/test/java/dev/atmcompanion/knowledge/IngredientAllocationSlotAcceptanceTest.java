package dev.atmcompanion.knowledge;

import org.junit.jupiter.api.Test;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class IngredientAllocationSlotAcceptanceTest {
    @Test void rejectsInvalidSlotIdentitiesInAlternatives() {
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(List.of(-1)), Map.of()));
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(List.of(36)), Map.of()));
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(Arrays.asList((Integer) null)), Map.of()));
    }

    @Test void rejectsInvalidSlotIdentitiesAndNullCountsInInventory() {
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(), Map.of(-1, 1)));
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(), Map.of(36, 1)));
        var nullKey = new LinkedHashMap<Integer, Integer>();
        nullKey.put(null, 1);
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(), nullKey));
        var counts = new LinkedHashMap<Integer, Integer>();
        counts.put(0, null);
        assertThrows(IllegalArgumentException.class, () -> IngredientAllocation.canSatisfy(List.of(), counts));
    }

    @Test void validAllocationAndInputsArePreserved() {
        var counts = new LinkedHashMap<>(Map.of(0, 1, 35, 1));
        assertTrue(IngredientAllocation.canSatisfy(List.of(List.of(0, 35), List.of(0)), counts));
        assertEquals(Map.of(0, 1, 35, 1), counts);
        assertFalse(IngredientAllocation.canSatisfy(List.of(List.of(35), List.of(35)), counts));
    }
}
