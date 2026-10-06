package dev.atmcompanion.state;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class InventoryTotalCountAcceptanceTest {
    @Test void sumsExactIdentityWithoutIntOverflow() {
        var inventory = new GameSnapshot.Inventory(List.of(
                new GameSnapshot.Item("minecraft:stone", 2_000_000_000, 0, false),
                new GameSnapshot.Item("minecraft:dirt", 5, 1, false),
                new GameSnapshot.Item("minecraft:stone", 2_000_000_000, 2, false)), 64, false);
        assertEquals(4_000_000_000L, inventory.totalCount("minecraft:stone"));
        assertEquals(5L, inventory.totalCount("minecraft:dirt"));
        assertEquals(0L, inventory.totalCount("minecraft:glass"));
        assertEquals(3, inventory.stacks().size());
        assertThrows(IllegalArgumentException.class, () -> inventory.totalCount(null));
    }
}
