package dev.atmcompanion.execution;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.planning.PlanResult;
import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;
import java.util.List;
import static dev.atmcompanion.knowledge.RecipeFixtures.*;
import static org.junit.jupiter.api.Assertions.*;

class ExecutionAssessorTest {
    private static final NormalizedRecipe RECIPE = recipe("fixture:stone", "minecraft:stone", 1, exact(0, "minecraft:cobblestone", 1));
    private static final OperationInputs.Result INPUTS = new OperationInputs.Result(true, false,
            List.of(new PlanResult.Resource("minecraft:cobblestone", 1)), "One real input");

    @Test
    void inventoryCraftingNeedsAnObservedFitAndUnlockButNoNearbyTable() {
        var ready = assess(context(crafting(true, true, Observation.available(true)), true, List.of(), List.of()));
        assertEquals("observed_conditions_met", ready.status());
        assertEquals("player_2x2", ready.station());
        assertEquals(1, ready.operations());
        assertFalse(ready.unverifiedConditions().isEmpty(), "A feasibility result must retain unverified interaction conditions");
        assertEquals("blocked", assess(context(crafting(true, true, Observation.available(false)), true, List.of(), List.of())).status());
        assertEquals("unknown", assess(context(crafting(true, true, Observation.unavailable("not observed")), true, List.of(), List.of())).status());
        assertEquals("unknown", assess(context(crafting(false, false, Observation.available(true)), true, List.of(), List.of())).status());
    }

    @Test
    void tableAccessChecksAndPartialNegativeObservationsStayDistinct() {
        var operation = crafting(false, true, Observation.available(true));
        assertEquals("blocked", assess(context(operation, true, List.of(), List.of())).status());
        assertEquals("unknown", assess(context(operation, false, List.of(), List.of())).status());
        var table = station("crafting", true, true, Observation.available(true), null);
        assertEquals("observed_conditions_met", assess(context(operation, true, List.of(table), List.of())).status());
        var far = station("crafting", false, true, Observation.available(true), null);
        assertEquals("approach_station", assess(context(operation, true, List.of(far), List.of())).nextAction().kind());
        var forbidden = station("crafting", true, false, Observation.available(true), null);
        assertEquals("blocked", assess(context(operation, true, List.of(forbidden), List.of())).status());
        var locked = station("crafting", true, true, Observation.available(false), null);
        assertEquals("blocked", assess(context(operation, true, List.of(locked), List.of())).status());
        var unknownLock = station("crafting", true, true, Observation.unavailable("unsupported"), null);
        assertEquals("unknown", assess(context(operation, true, List.of(unknownLock), List.of())).status());
    }

    @Test
    void occupiedInputAndBlockedOutputNeverBecomePlayerOwnedMaterials() {
        assertEquals("blocked", furnace(details(1, 0, 0, 201, true, true, null, List.of()), List.of()).status());
        assertEquals("blocked", furnace(details(0, 0, 64, 201, true, false, null, List.of()), List.of()).status());
        assertEquals("blocked", furnace(details(0, 0, 0, 201, false, true, null, List.of()), List.of()).status());
        var unknownOutput = new ExecutionContext.Details(slots(0, 0, 0), false, false, Observation.available(timers(201)),
                Observation.available(true), Observation.unavailable("predicate not evaluated"), Observation.available(0), 0, List.of());
        assertEquals("unknown", furnace(unknownOutput, List.of()).status());
    }

    @Test
    void existingHeatAccountsForTheNextVanillaTickBeforeCooking() {
        var justEnough = furnace(details(0, 0, 0, 201, true, true, null, List.of()), List.of());
        assertEquals("observed_conditions_met", justEnough.status());
        assertEquals(List.of(new ExecutionAssessment.FuelReservation("station_heat", -1, null, 0, 200)), justEnough.fuel());
        assertEquals("blocked", furnace(details(0, 0, 0, 200, true, true, null, List.of()), List.of()).status(),
                "BurnTime=200 loses one tick before the first new input operation is cooked");
    }

    @Test
    void oneUnreservedCompatibleFuelItemCanCompleteOneOperation() {
        var details = details(0, 0, 0, 0, true, true, null, List.of(2));
        var ready = furnace(details, List.of(fuel(2, "minecraft:coal", 3, 2, Observation.available(1600))));
        assertEquals("observed_conditions_met", ready.status());
        assertEquals(1, ready.operations());
        assertEquals(List.of(new ExecutionAssessment.FuelReservation("player", 2, "minecraft:coal", 1, 1600)), ready.fuel());
        assertEquals(List.of(new PlanResult.Resource("minecraft:cobblestone", 1)), ready.inputs());
        assertEquals("blocked", furnace(details, List.of(fuel(2, "minecraft:coal", 3, 0, Observation.available(1600)))).status(),
                "Fuel reserved as full-path material is physically present but unavailable for burning");
        assertEquals("blocked", furnace(details, List.of(fuel(3, "minecraft:coal", 3, 3, Observation.available(1600)))).status(),
                "Registry identity alone cannot replace a component-sensitive fuel-slot compatibility observation");
    }

    @Test
    void fuelQueuesAreNotInventedFromManyShortBurnItems() {
        var details = details(0, 0, 0, 0, true, true, null, List.of(2));
        var shortFuel = fuel(2, "minecraft:stick", 64, 64, Observation.available(100));
        var result = furnace(details, List.of(shortFuel));
        assertEquals("blocked", result.status());
        assertEquals("supply_fuel", result.nextAction().kind());
        assertTrue(result.fuel().isEmpty());
        var combined = furnace(details(0, 0, 0, 101, true, true, null, List.of(2)), List.of(shortFuel));
        assertEquals("observed_conditions_met", combined.status());
        assertEquals(200, combined.fuel().stream().mapToLong(ExecutionAssessment.FuelReservation::burnTicks).sum());
    }

    @Test
    void ExistingFuelIsBoundedToOneIgnitionAndUnknownBurnTimesStayUnknown() {
        var ready = furnace(details(0, 12, 0, 0, true, true, 200, List.of()), List.of());
        assertEquals("observed_conditions_met", ready.status());
        assertEquals(List.of(new ExecutionAssessment.FuelReservation("station", 1, "minecraft:coal", 1, 200)), ready.fuel());
        assertEquals("unknown", furnace(details(0, 12, 0, 0, true, true, 100, List.of()), List.of()).status());
        assertEquals("unknown", furnace(details(0, 1, 0, 0, true, true, null, List.of()), List.of()).status());
        assertEquals("unknown", furnace(details(0, 0, 0, 0, true, true, null, List.of(2)),
                List.of(fuel(2, "minecraft:coal", 1, 1, Observation.unavailable("fuel hook failed")))).status());
    }

    @Test
    void cookingRequiresOneObservedMatchingInputAndUniqueRecipe() {
        var station = station("furnace", true, true, Observation.available(true), details(0, 0, 0, 201, true, true, null, List.of()));
        for (Observation<Boolean> unique : List.of(Observation.available(false), Observation.<Boolean>unavailable("budget"))) {
            var op = cooking("furnace", unique, Observation.available(true), "minecraft:cobblestone");
            assertEquals("unknown", assess(context(op, true, List.of(station), List.of())).status());
        }
        var nonmatching = cooking("furnace", Observation.available(true), Observation.available(false), "minecraft:cobblestone");
        assertEquals("unknown", assess(context(nonmatching, true, List.of(station), List.of())).status());
        var differentInput = cooking("furnace", Observation.available(true), Observation.available(true), "minecraft:deepslate");
        assertEquals("unknown", assess(context(differentInput, true, List.of(station), List.of())).status());
        var twoInputs = new OperationInputs.Result(true, false, List.of(new PlanResult.Resource("minecraft:cobblestone", 2)), "batch");
        assertEquals("unknown", ExecutionAssessor.assess(plan("materials_ready"), RECIPE, twoInputs,
                context(cooking(), true, List.of(station), List.of())).status());
    }

    @Test
    void campfireRequiresLitDryAndFreeSlotWithoutAssumingDroppedOutputOwnership() {
        var op = cooking("campfire", Observation.available(true), Observation.available(true), "minecraft:cobblestone");
        for (int mode = 0; mode < 4; mode++) {
            var details = new ExecutionContext.Details(List.of(), mode != 1, mode == 2, Observation.unavailable("not needed"),
                    Observation.unavailable("not needed"), Observation.unavailable("drops into world"), Observation.available(0), mode == 3 ? 0 : 1, List.of());
            var result = assess(context(op, true, List.of(station("campfire", true, true, Observation.available(true), details)), List.of()));
            assertEquals(mode == 0 ? "observed_conditions_met" : "blocked", result.status());
            assertTrue(result.fuel().isEmpty());
            if (mode == 0) assertTrue(result.nextAction().reason().contains("drops into the world"));
        }
    }

    @Test
    void availableStationBeatsEarlierBlockedOrUninspectedCandidates() {
        var unknown = station("furnace", true, true, Observation.available(true), null);
        var occupied = station("furnace", true, true, Observation.available(true), details(1, 0, 0, 201, true, true, null, List.of()));
        var ready = station("furnace", true, true, Observation.available(true), details(0, 0, 0, 201, true, true, null, List.of()));
        assertEquals("observed_conditions_met", assess(context(cooking(), true, List.of(unknown, occupied, ready), List.of())).status());
    }

    @Test
    void ownedGoalAndUnavailableOrTruncatedInputsNeverRequestACraft() {
        var context = context(cooking(), true, List.of(), List.of());
        assertEquals("not_needed", ExecutionAssessor.assess(plan("already_owned"), RECIPE, INPUTS, context).status());
        var absent = new OperationInputs.Result(false, false, List.of(), "Inputs not present", "missing");
        var limited = new OperationInputs.Result(false, true, List.of(), "Search bound reached");
        assertEquals("blocked", ExecutionAssessor.assess(plan("materials_ready"), RECIPE, absent, context).status());
        assertEquals("unknown", ExecutionAssessor.assess(plan("materials_ready"), RECIPE, limited, context).status());
        assertNull(ExecutionAssessor.assess(plan("materials_ready"), RECIPE, absent, context).nextAction());
    }

    @Test
    void missingProvenanceIsUnknownWhileAValidatedInventoryShortageIsBlocked() {
        var missingProvenance = new PlanResult.Step(RECIPE.id(), RECIPE.output().item(), 1, 1, RECIPE.type(), 0, List.of());
        var unknown = OperationInputs.select(RECIPE, missingProvenance, java.util.Map.of("minecraft:cobblestone", 1L));
        assertEquals("unavailable", unknown.status());
        assertEquals("unknown", ExecutionAssessor.assess(plan("materials_ready"), RECIPE, unknown,
                context(cooking(), true, List.of(), List.of())).status(), "A missing allocation is not evidence that inventory is insufficient");

        var validated = new PlanResult.Step(RECIPE.id(), RECIPE.output().item(), 1, 1, RECIPE.type(), 0, List.of(),
                List.of(new PlanResult.AllocatedIngredient(0, "minecraft:cobblestone", 1)));
        var shortage = OperationInputs.select(RECIPE, validated, java.util.Map.of());
        assertEquals("missing", shortage.status());
        assertEquals("blocked", ExecutionAssessor.assess(plan("materials_ready"), RECIPE, shortage,
                context(cooking(), true, List.of(), List.of())).status());
        assertThrows(IllegalArgumentException.class, () -> new OperationInputs.Result(true, false, List.of(), "contradiction", "missing"));
        assertThrows(IllegalArgumentException.class, () -> new OperationInputs.Result(false, true, List.of(), "contradiction", "unavailable"));
    }

    private static ExecutionAssessment assess(ExecutionContext context) { return ExecutionAssessor.assess(plan("materials_ready"), RECIPE, INPUTS, context); }
    private static ExecutionAssessment furnace(ExecutionContext.Details details, List<ExecutionContext.FuelSlot> fuel) {
        return assess(context(cooking(), true, List.of(station("furnace", true, true, Observation.available(true), details)), fuel));
    }
    private static PlanResult plan(String status) {
        return new PlanResult(2, "minecraft:stone", 40, status, List.of(new PlanResult.Resource("minecraft:cobblestone", 40)),
                List.of(), List.of(), null, List.of(), List.of(), new PlanResult.Metrics(1, 0, 0, false, true, 0), List.of());
    }
    private static ExecutionContext.Operation crafting(boolean small, boolean large, Observation<Boolean> unlock) {
        return new ExecutionContext.Operation(RECIPE.id(), "crafting", "crafting", small, large, unlock,
                Observation.unavailable("not cooking"), Observation.unavailable("not cooking"), Observation.unavailable("not cooking"), -1, null);
    }
    private static ExecutionContext.Operation cooking() { return cooking("furnace", Observation.available(true), Observation.available(true), "minecraft:cobblestone"); }
    private static ExecutionContext.Operation cooking(String kind, Observation<Boolean> unique, Observation<Boolean> matches, String input) {
        return new ExecutionContext.Operation(RECIPE.id(), "cooking", kind, false, false, Observation.available(true), Observation.available(200), unique, matches, 0, input);
    }
    private static ExecutionContext context(ExecutionContext.Operation op, boolean complete, List<ExecutionContext.Station> stations, List<ExecutionContext.FuelSlot> fuel) {
        return new ExecutionContext(1, "2026-09-22T00:00:00Z", "minecraft:overworld",
                new ExecutionContext.Scan(8, 4913, complete ? 4913 : 10, complete ? 4913 : 10, 0, stations.size(), false, !complete, 0, 0),
                stations, Observation.available(op), fuel, List.of());
    }
    private static ExecutionContext.Station station(String kind, boolean reach, boolean permission, Observation<Boolean> lock, ExecutionContext.Details details) {
        return new ExecutionContext.Station("minecraft:" + (kind.equals("crafting") ? "crafting_table" : kind), kind, 1, 64, 1, 2,
                reach, permission, lock, details == null ? Observation.unavailable("not inspected") : Observation.available(details));
    }
    private static ExecutionContext.Details details(int input, int fuel, int output, int heat, boolean inputFits, boolean outputFits, Integer burn, List<Integer> compatible) {
        return new ExecutionContext.Details(slots(input, fuel, output), heat > 0, false, Observation.available(timers(heat)),
                Observation.available(inputFits), Observation.available(outputFits), burn == null ? Observation.unavailable("not known") : Observation.available(burn), 0, compatible);
    }
    private static List<ExecutionContext.Stack> slots(int input, int fuel, int output) {
        return List.of(new ExecutionContext.Stack(0, input == 0 ? null : "minecraft:cobblestone", input, false),
                new ExecutionContext.Stack(1, fuel == 0 ? null : "minecraft:coal", fuel, false),
                new ExecutionContext.Stack(2, output == 0 ? null : "minecraft:stone", output, false));
    }
    private static ExecutionContext.Timers timers(int remaining) { return new ExecutionContext.Timers(remaining, 0, 200, List.of(), List.of()); }
    private static ExecutionContext.FuelSlot fuel(int slot, String item, int count, int free, Observation<Integer> burn) {
        return new ExecutionContext.FuelSlot(slot, item, count, free, burn, false);
    }
}
