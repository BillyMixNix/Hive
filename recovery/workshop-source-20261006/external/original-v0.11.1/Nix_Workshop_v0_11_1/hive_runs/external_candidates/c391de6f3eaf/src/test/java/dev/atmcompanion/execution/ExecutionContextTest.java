package dev.atmcompanion.execution;

import com.google.gson.Gson;
import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ExecutionContextTest {
    @Test
    void absenceIsCompleteOnlyWithinAFullyInspectedLoadedScope() {
        assertTrue(new ExecutionContext.Scan(0, 1, 1, 1, 0, 0, false, false, 0, 0).complete());
        assertFalse(new ExecutionContext.Scan(1, 27, 26, 26, 0, 0, false, false, 0, 0).complete());
        assertFalse(new ExecutionContext.Scan(1, 27, 27, 26, 1, 0, false, false, 0, 0).complete());
        assertFalse(new ExecutionContext.Scan(1, 27, 27, 27, 0, 2, true, false, 0, 0).complete());
        assertFalse(new ExecutionContext.Scan(1, 27, 27, 27, 0, 0, false, true, 0, 0).complete());
    }

    @Test
    void unknownStationContentsCannotBecomeKnownEmptyThroughSerialization() {
        var station = new ExecutionContext.Station("minecraft:furnace", "furnace", 1, 2, 3, 4, true, true,
                Observation.unavailable("Lock access was not inspected"), Observation.unavailable("Deep inspection limit reached"));
        var context = context(List.of(station), List.of());
        var gson = new Gson();
        var restored = gson.fromJson(gson.toJson(context), ExecutionContext.class);

        assertEquals(context, restored);
        assertNull(restored.stations().getFirst().details().data());
        assertTrue(restored.stations().getFirst().details().detail().contains("limit"));
        var emptySlot = new ExecutionContext.Stack(0, null, 0, false);
        assertEquals(0, emptySlot.count());
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Stack(0, null, 0, true));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Stack(0, "minecraft:coal", 0, false));
    }

    @Test
    void reservedFuelIsKnownPresentButUnavailableForDoubleSpending() {
        var fuel = new ExecutionContext.FuelSlot(4, "fixture:component_fuel", 2, 0, Observation.available(400), true);
        var context = context(List.of(), List.of(fuel));
        var restored = new Gson().fromJson(new Gson().toJson(context), ExecutionContext.class);

        assertEquals(2, restored.fuelSlots().getFirst().count());
        assertEquals(0, restored.fuelSlots().getFirst().availableAfterReservation());
        assertTrue(restored.fuelSlots().getFirst().hasComponents());
        assertEquals(400, restored.fuelSlots().getFirst().burnTicksPerItem().data());
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.FuelSlot(0, "fixture:fuel", 1, 2, Observation.available(400), false));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.FuelSlot(0, "fixture:fuel", 1, 1, Observation.available(-1), false));
    }

    @Test
    void publishedNestedObservationsAreDetachedImmutableCopies() {
        var inputStacks = new ArrayList<>(List.of(new ExecutionContext.Stack(0, "fixture:input", 3, false)));
        var compatibleSlots = new ArrayList<>(List.of(2));
        var details = new ExecutionContext.Details(inputStacks, false, false, Observation.unavailable("Timers unavailable"),
                Observation.available(true), Observation.available(false), Observation.available(400), 0, compatibleSlots);
        var stations = new ArrayList<>(List.of(new ExecutionContext.Station("minecraft:furnace", "furnace", 0, 0, 0, 0, true, true,
                Observation.available(true), Observation.available(details))));
        var fuels = new ArrayList<>(List.of(new ExecutionContext.FuelSlot(2, "fixture:fuel", 1, 1, Observation.available(400), false)));
        var context = context(stations, fuels);
        inputStacks.clear(); compatibleSlots.clear(); stations.clear(); fuels.clear();

        assertEquals(1, context.stations().size());
        assertEquals("fixture:input", context.stations().getFirst().details().data().stacks().getFirst().item());
        assertEquals(List.of(2), context.stations().getFirst().details().data().compatibleFuelSlots());
        assertEquals(1, context.fuelSlots().size());
        assertThrows(UnsupportedOperationException.class, () -> context.stations().clear());
        assertThrows(UnsupportedOperationException.class, () -> details.stacks().clear());
    }

    @Test
    void malformedScanAndCookingFactsAreRejectedInsteadOfLookingReady() {
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Scan(1, 27, 27, 26, 0, 0, false, false, 0, 0));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Scan(1, 27, 27, 27, 0, 0, false, false, 9, 0));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Scan(1, 27, 27, 27, 0, 0, false, false, 0, 4097));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Timers(-1, 0, 200, List.of(), List.of()));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Timers(0, 0, 200, List.of(0), List.of(200)));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Operation("fixture:cook", "smelting", "furnace", false, false,
                Observation.available(true), Observation.available(0), Observation.available(true), Observation.available(true), 0, "fixture:input"));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionContext.Operation("fixture:cook", "smelting", "furnace", false, false,
                Observation.available(true), Observation.available(200), Observation.available(true), Observation.available(true), -1, "fixture:input"));
    }

    private static ExecutionContext context(List<ExecutionContext.Station> stations, List<ExecutionContext.FuelSlot> fuel) {
        return new ExecutionContext(1, "2026-09-22T00:00:00Z", "minecraft:overworld",
                new ExecutionContext.Scan(1, 27, 27, 27, 0, stations.size(), false, false, 0, 0),
                stations, Observation.unavailable("No operation selected"), fuel, List.of("Observed test facts only"));
    }
}
