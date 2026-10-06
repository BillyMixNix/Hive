package dev.atmcompanion.knowledge;

import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import static org.junit.jupiter.api.Assertions.*;

class RecipeSelectionBestOfAcceptanceTest {
    @Test void selectsNaturalMinimumWithoutMutatingInput() {
        var high = new RecipeSelection(1, 0, "z");
        var tie = new RecipeSelection(0, 4, "b");
        var best = new RecipeSelection(0, 4, "a");
        var candidates = new ArrayList<>(List.of(high, tie, best));
        assertEquals(Optional.of(best), RecipeSelection.bestOf(candidates));
        assertEquals(List.of(high, tie, best), candidates);
        assertEquals(Optional.empty(), RecipeSelection.bestOf(List.of()));
        assertThrows(IllegalArgumentException.class, () -> RecipeSelection.bestOf(null));
        assertThrows(IllegalArgumentException.class, () -> RecipeSelection.bestOf(java.util.Arrays.asList(best, null)));
    }
}
