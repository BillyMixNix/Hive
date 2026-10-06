package dev.atmcompanion.execution;

import dev.atmcompanion.state.Observation;
import java.time.Instant;
import java.util.List;
import java.util.Objects;

/** Detached observations for one request; nearby containers are never player-owned resources. */
public record ExecutionContext(int schemaVersion, String timestamp, String dimension, Scan scan,
                               List<Station> stations, Observation<Operation> operation,
                               List<FuelSlot> fuelSlots, List<String> limitations) {
    public static final int SCHEMA_VERSION = 1;
    public ExecutionContext {
        if (schemaVersion != SCHEMA_VERSION) throw new IllegalArgumentException("Unsupported execution schema");
        Instant.parse(timestamp); id(dimension); Objects.requireNonNull(scan); Objects.requireNonNull(operation);
        stations = List.copyOf(stations); fuelSlots = List.copyOf(fuelSlots); limitations = List.copyOf(limitations);
        if (stations.size() > 32 || fuelSlots.size() > 36 || limitations.size() > 24) throw new IllegalArgumentException("Execution context bounds exceeded");
    }
    public record Scan(int radius, int totalPositions, int scannedPositions, int loadedPositions,
                       int unloadedPositions, int discoveredStations, boolean recordsTruncated,
                       boolean budgetExceeded, int deepInspections, int predicateChecks) {
        public Scan {
            if (radius < 0 || radius > 8 || totalPositions < 0 || totalPositions > 4913
                    || scannedPositions < 0 || scannedPositions > totalPositions || loadedPositions < 0 || unloadedPositions < 0
                    || loadedPositions + unloadedPositions != scannedPositions || discoveredStations < 0 || discoveredStations > loadedPositions
                    || deepInspections < 0 || deepInspections > 8 || predicateChecks < 0 || predicateChecks > 4096)
                throw new IllegalArgumentException("Invalid scan coverage");
        }
        public boolean complete() { return scannedPositions == totalPositions && unloadedPositions == 0 && !recordsTruncated && !budgetExceeded; }
    }
    public record Operation(String recipeId, String kind, String stationKind, boolean fits2x2, boolean fits3x3,
                            Observation<Boolean> unlockAllowed, Observation<Integer> cookingTicks,
                            Observation<Boolean> uniqueCookingMatch, Observation<Boolean> playerInputMatches,
                            int selectedInputSlot, String selectedInputItem) {
        public Operation {
            id(recipeId); Objects.requireNonNull(kind); Objects.requireNonNull(stationKind);
            Objects.requireNonNull(unlockAllowed); Objects.requireNonNull(cookingTicks);
            Objects.requireNonNull(uniqueCookingMatch); Objects.requireNonNull(playerInputMatches);
            if (selectedInputSlot < -1 || selectedInputSlot >= 36 || ((selectedInputSlot == -1) != (selectedInputItem == null)))
                throw new IllegalArgumentException("Invalid selected player input");
            if (selectedInputItem != null) id(selectedInputItem);
            if (cookingTicks.data() != null && cookingTicks.data() <= 0) throw new IllegalArgumentException("Invalid cooking duration");
        }
    }
    public record Station(String blockId, String kind, int x, int y, int z, double distanceSquared,
                          boolean withinReach, boolean vanillaMayInteract, Observation<Boolean> lockAllows,
                          Observation<Details> details) {
        public Station {
            id(blockId); Objects.requireNonNull(kind); Objects.requireNonNull(lockAllows); Objects.requireNonNull(details);
            if (!Double.isFinite(distanceSquared) || distanceSquared < 0) throw new IllegalArgumentException("Invalid station distance");
        }
    }
    public record Details(List<Stack> stacks, boolean lit, boolean waterlogged, Observation<Timers> timers,
                          Observation<Boolean> inputCompatible, Observation<Boolean> outputCompatible,
                          Observation<Integer> fuelTicksPerItem, int freeCampfireSlots, List<Integer> compatibleFuelSlots) {
        public Details {
            stacks = List.copyOf(stacks); Objects.requireNonNull(timers); Objects.requireNonNull(inputCompatible);
            Objects.requireNonNull(outputCompatible); Objects.requireNonNull(fuelTicksPerItem);
            compatibleFuelSlots = List.copyOf(compatibleFuelSlots);
            if (stacks.size() > 4 || freeCampfireSlots < 0 || freeCampfireSlots > 4
                    || compatibleFuelSlots.size() > 36 || compatibleFuelSlots.stream().anyMatch(slot -> slot < 0 || slot >= 36)
                    || (fuelTicksPerItem.data() != null && fuelTicksPerItem.data() < 0)) throw new IllegalArgumentException("Invalid station details");
        }
    }
    /** Empty slots have null item, count zero, and no component claim. */
    public record Stack(int slot, String item, int count, boolean hasComponents) {
        public Stack {
            if (slot < 0 || slot > 3 || count < 0 || ((item == null) != (count == 0)) || (item == null && hasComponents))
                throw new IllegalArgumentException("Invalid station stack");
            if (item != null) id(item);
        }
    }
    public record Timers(int remainingBurnTicks, int cookingProgress, int cookingTotalTime,
                         List<Integer> slotProgress, List<Integer> slotTotalTimes) {
        public Timers {
            slotProgress = List.copyOf(slotProgress); slotTotalTimes = List.copyOf(slotTotalTimes);
            if (remainingBurnTicks < 0 || cookingProgress < 0 || cookingTotalTime < 0
                    || slotProgress.size() != slotTotalTimes.size() || (slotProgress.size() != 0 && slotProgress.size() != 4)
                    || slotProgress.stream().anyMatch(n -> n < 0) || slotTotalTimes.stream().anyMatch(n -> n < 0))
                throw new IllegalArgumentException("Invalid cooking timers");
        }
    }
    public record FuelSlot(int slot, String item, int count, int availableAfterReservation,
                           Observation<Integer> burnTicksPerItem, boolean hasComponents) {
        public FuelSlot {
            id(item); Objects.requireNonNull(burnTicksPerItem);
            if (slot < 0 || slot >= 36 || count < 1 || availableAfterReservation < 0 || availableAfterReservation > count
                    || (burnTicksPerItem.data() != null && burnTicksPerItem.data() < 0)) throw new IllegalArgumentException("Invalid fuel observation");
        }
    }
    private static void id(String value) {
        if (value == null || value.length() > 256 || !value.matches("[a-z0-9_.-]+:[a-z0-9/._-]+"))
            throw new IllegalArgumentException("Invalid registry identity");
    }
}

// NFRT source-sensitivity probe: no behavior change.
