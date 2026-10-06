package dev.atmcompanion.execution;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.planning.PlanResult;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** Selects one operation using only the exact per-position members chosen by the complete material path. */
public final class OperationInputs {
    public static final int MAX_NODES = 512;
    public static final int MAX_REQUIRED_UNITS = 64;
    private static final int MAX_INVENTORY_ITEMS = 256;
    private static final int MAX_ALLOCATIONS = NormalizedRecipe.MAX_REQUIREMENTS * NormalizedRecipe.MAX_ALTERNATIVES;
    private OperationInputs() { }

    public record Result(boolean ready, boolean truncated, List<PlanResult.Resource> inputs, String detail, String status) {
        public Result(boolean ready, boolean truncated, List<PlanResult.Resource> inputs, String detail) {
            this(ready, truncated, inputs, detail, ready ? "available" : truncated ? "limited" : "unavailable");
        }
        public Result {
            inputs = List.copyOf(inputs);
            if (!List.of("available", "missing", "unavailable", "limited").contains(status)
                    || ready != status.equals("available") || truncated != status.equals("limited"))
                throw new IllegalArgumentException("Contradictory operation input status");
        }
    }

    public static Result select(NormalizedRecipe recipe, PlanResult.Step step, Map<String, Long> inventory) {
        if (recipe == null || step == null || inventory == null) return unavailable("Recipe, step or inventory evidence is unavailable");
        if (!recipe.dependencySupported() || recipe.output() == null || !recipe.output().fixed()
                || recipe.output().hasNonDefaultComponents()) return unavailable("Recipe has unsupported material semantics");
        if (!recipe.id().equals(step.recipeId()) || !recipe.output().item().equals(step.output())
                || !recipe.type().equals(step.type()) || step.crafts() < 1)
            return unavailable("Step does not identify a supported batch of this recipe");
        if (inventory.size() > MAX_INVENTORY_ITEMS || step.ingredients().size() > MAX_ALLOCATIONS)
            return limited("Inventory or allocation input exceeds the inspection bound");
        if (step.ingredients().isEmpty()) return unavailable("Exact selected ingredient allocations are unavailable");

        TreeMap<String, Long> available = new TreeMap<>();
        for (var entry : inventory.entrySet()) {
            if (entry.getKey() == null || entry.getKey().length() > NormalizedRecipe.MAX_ID_LENGTH
                    || entry.getValue() == null || entry.getValue() < 0)
                return unavailable("Inventory contains malformed item counts");
            if (entry.getValue() > 0) available.put(entry.getKey(), entry.getValue());
        }
        TreeMap<Integer, NormalizedRecipe.Requirement> requirements = new TreeMap<>();
        long units = 0;
        for (var requirement : recipe.ingredients()) {
            if (!requirement.supported() || requirements.putIfAbsent(requirement.position(), requirement) != null)
                return unavailable("Recipe requirements are unsupported or contain duplicate positions");
            units += requirement.count();
            if (units > MAX_REQUIRED_UNITS) return limited("One operation exceeds the 64-unit inspection bound");
        }
        if (units == 0) return unavailable("No material requirements were established for this operation");
        TreeMap<Integer, TreeMap<String, Long>> permitted = new TreeMap<>();
        try {
            if (Math.multiplyExact(step.crafts(), recipe.output().count()) != step.outputQuantity())
                return unavailable("Step output quantity disagrees with its batch size");
            for (var allocation : step.ingredients()) {
                var requirement = requirements.get(allocation.position());
                if (requirement == null || allocation.item() == null || allocation.quantity() < 1
                        || !requirement.alternatives().contains(allocation.item()))
                    return unavailable("Selected allocation contains an unknown position or unsupported member");
                permitted.computeIfAbsent(allocation.position(), ignored -> new TreeMap<>())
                        .merge(allocation.item(), allocation.quantity(), Math::addExact);
            }
            for (var requirement : requirements.values()) {
                Map<String, Long> allocation = permitted.get(requirement.position());
                if (allocation == null) return unavailable("Selected allocation is missing an ingredient position");
                long allocated = 0;
                for (long count : allocation.values()) allocated = Math.addExact(allocated, count);
                if (allocated != Math.multiplyExact(step.crafts(), requirement.count()))
                    return unavailable("Selected allocation does not cover exactly the full planned batch");
            }
        } catch (ArithmeticException exception) {
            return unavailable("Selected allocation quantities overflow the supported representation");
        }

        List<Position> positions = new ArrayList<>();
        for (var requirement : requirements.values()) {
            TreeMap<String, Long> quota = permitted.get(requirement.position());
            List<String> candidates = quota.keySet().stream().filter(item -> available.getOrDefault(item, 0L) > 0).toList();
            long capacity = 0;
            for (String item : candidates) capacity += Math.min((long) requirement.count(), Math.min(quota.get(item), available.get(item)));
            if (capacity < requirement.count()) return missing("Current inventory cannot supply the selected members for one operation");
            positions.add(new Position(requirement.position(), requirement.count(), candidates, quota));
        }
        positions.sort(Comparator.comparingInt((Position position) -> position.candidates().size())
                .thenComparing(Comparator.comparingInt(Position::count).reversed()).thenComparingInt(Position::position));
        Search search = new Search(positions, available);
        if (!search.assign(0, 0, 0)) return search.truncated
                ? limited("One-operation allocation reached its 512-node search bound; readiness is unknown")
                : missing("Selected ingredient positions compete for the same current inventory; one operation is not supplied");
        List<PlanResult.Resource> inputs = search.used.entrySet().stream()
                .map(entry -> new PlanResult.Resource(entry.getKey(), entry.getValue())).toList();
        return new Result(true, false, inputs, "Exactly one operation is supplied by current inventory using the full path's selected members");
    }
    private static Result unavailable(String detail) { return new Result(false, false, List.of(), detail); }
    private static Result missing(String detail) { return new Result(false, false, List.of(), detail, "missing"); }
    private static Result limited(String detail) { return new Result(false, true, List.of(), detail); }
    private record Position(int position, int count, List<String> candidates, TreeMap<String, Long> quota) { }
    private static final class Search {
        final List<Position> positions;
        final TreeMap<String, Long> available;
        final TreeMap<String, Long> used = new TreeMap<>();
        int nodes;
        boolean truncated;
        Search(List<Position> positions, TreeMap<String, Long> available) { this.positions = positions; this.available = available; }
        boolean assign(int positionIndex, int assigned, int minimumOption) {
            if (positionIndex == positions.size()) return true;
            Position position = positions.get(positionIndex);
            if (assigned == position.count()) return assign(positionIndex + 1, 0, 0);
            // Canonical order within one position eliminates permutations of the same multiset.
            for (int option = minimumOption; option < position.candidates().size(); option++) {
                String item = position.candidates().get(option);
                long remaining = available.getOrDefault(item, 0L);
                long quota = position.quota().get(item);
                if (remaining == 0 || quota == 0) continue;
                if (nodes >= MAX_NODES) { truncated = true; return false; }
                nodes++;
                available.put(item, remaining - 1);
                position.quota().put(item, quota - 1);
                used.merge(item, 1L, Long::sum);
                if (assign(positionIndex, assigned + 1, option)) return true;
                available.put(item, remaining);
                position.quota().put(item, quota);
                long previouslyUsed = used.get(item) - 1;
                if (previouslyUsed == 0) used.remove(item); else used.put(item, previouslyUsed);
                if (truncated) return false;
            }
            return false;
        }
    }
}
