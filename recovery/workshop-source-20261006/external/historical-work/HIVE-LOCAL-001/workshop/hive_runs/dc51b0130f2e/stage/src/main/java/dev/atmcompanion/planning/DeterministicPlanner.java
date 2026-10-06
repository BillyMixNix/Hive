package dev.atmcompanion.planning;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.knowledge.RecipeIndex;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

/** Bounded material-path search. Never claims execution readiness or mutates the actual inventory. */
public final class DeterministicPlanner {
    public static final long MAX_QUANTITY = 1_000_000;
    public record Limits(int depth, int nodes, int recipesPerOutput, int alternatives, int beamWidth) {
        public Limits {
            if (depth < 1 || depth > 24 || nodes < 1 || nodes > 4096 || recipesPerOutput < 1 || recipesPerOutput > 32
                    || alternatives < 1 || alternatives > 32 || beamWidth < 1 || beamWidth > 16)
                throw new IllegalArgumentException("Planner limits outside safe bounds");
        }
        public static Limits defaults() { return new Limits(10, 768, 6, 6, 6); }
    }
    private final Limits limits;
    public DeterministicPlanner() { this(Limits.defaults()); }
    public DeterministicPlanner(Limits limits) { this.limits = Objects.requireNonNull(limits); }

    public PlanResult plan(RecipeIndex index, String goal, long quantity, Map<String, Long> inventory) {
        return planCandidates(index, goal, quantity, inventory).getFirst();
    }
    /** Material candidates share a global cap, with independent quotas for distinct root routes. */
    public List<PlanResult> planCandidates(RecipeIndex index, String goal, long quantity, Map<String, Long> inventory) {
        Objects.requireNonNull(index);
        validateItem(goal);
        checkQuantity(quantity);
        Objects.requireNonNull(inventory);
        if (inventory.size() > 256) throw new IllegalArgumentException("Inventory input too large");
        State start = new State();
        inventory.forEach((item, count) -> {
            validateItem(item);
            if (count == null || count < 0 || count > MAX_QUANTITY) throw new IllegalArgumentException("Invalid inventory quantity");
            if (count > 0) start.original.put(item, count);
        });
        boolean alreadyOwned = start.original.getOrDefault(goal, 0L) >= quantity;
        long began = System.nanoTime();
        Budget budget = new Budget(index);
        List<State> candidates = trim(resolve(goal, quantity, start, Set.of(), 0, budget), budget);
        long elapsed = System.nanoTime() - began;
        List<PlanResult> reports = new ArrayList<>();
        for (State chosen : candidates) reports.add(report(index, goal, quantity, alreadyOwned, chosen, candidates, budget, elapsed));
        return List.copyOf(reports);
    }
    private PlanResult report(RecipeIndex index, String goal, long quantity, boolean alreadyOwned, State chosen,
                              List<State> candidates, Budget budget, long elapsed) {
        String status = alreadyOwned ? "already_owned" : chosen.issues.stream().anyMatch(i -> i.kind().equals("search_limit")) ? "search_limited"
                : !chosen.issues.isEmpty() ? "unsupported" : chosen.missing.isEmpty() ? "materials_ready" : "blocked";
        List<String> limitations = new ArrayList<>(List.of(
                "Material planning only; crafting access, recipe unlocks, fuel, machines, energy, fluids, and execution are not verified.",
                "Only main inventory slots 0..35; equipment, nested inventories and storage networks are not included.",
                "Future outputs are hypothetical until every prerequisite is satisfied; they are never reported as currently owned.",
                "Crafting remainders/byproducts are not credited. Route selection is bounded and may miss a better allocation."));
        if (!index.complete()) limitations.add("Recipe knowledge has unknown or truncated outputs; no indexed route does not prove no route exists.");
        if (budget.truncated) limitations.add("Search limit reached: showing the selected path discovered within the deterministic budget.");
        List<PlanResult.Alternative> alternatives = candidates.stream().filter(s -> s != chosen).limit(limits.beamWidth - 1L)
                .map(s -> new PlanResult.Alternative(rootRecipe(s), sum(s.missing), s.issues.size(), s.steps.size(),
                        resources(s.missing).stream().limit(8).toList(), s.issues.stream().limit(8).toList(), next(goal, quantity, s, alreadyOwned), "unknown")).toList();
        return new PlanResult(2, goal, quantity, status, resources(chosen.usedOriginal), resources(chosen.missing),
                chosen.steps, next(goal, quantity, chosen, alreadyOwned), alternatives, chosen.issues,
                new PlanResult.Metrics(index.generation(), budget.nodes, chosen.depth, budget.truncated, index.complete(), elapsed), limitations);
    }

    private List<State> resolve(String item, long amount, State input, Set<String> ancestors, int depth, Budget budget) {
        State base = input.copy();
        base.depth = Math.max(base.depth, depth);
        long remaining = amount - take(base, item, amount);
        if (remaining == 0) return List.of(base);
        if (amount > MAX_QUANTITY || depth > limits.depth || !budget.expand()) {
            return limited(base, item, remaining, "Dependency depth, quantity or expanded-node budget reached", budget);
        }
        if (ancestors.contains(item)) {
            base.issues.add(new PlanResult.Issue(item, remaining, "cycle", "Dependency cycle reaches " + item + "; this route cannot be expanded further"));
            return List.of(base);
        }
        var routes = budget.index.recipesFor(item);
        if (routes.isEmpty()) {
            add(base.missing, item, remaining);
            return List.of(base);
        }
        Set<String> path = new LinkedHashSet<>(ancestors);
        path.add(item);
        if (routes.size() > limits.recipesPerOutput || budget.index.recipesForTruncated(item)) budget.truncated = true;
        List<State> results = new ArrayList<>();
        // Supported material models are considered before opaque previews, then stable registry IDs.
        List<NormalizedRecipe> ordered = routes.stream().sorted(Comparator.comparing((NormalizedRecipe r) -> !r.dependencySupported()).thenComparing(NormalizedRecipe::id)).toList();
        var retainedRoutes = ordered.stream().limit(limits.recipesPerOutput).toList();
        int remainingRoots = retainedRoutes.size();
        for (NormalizedRecipe route : retainedRoutes) {
            if (depth == 0) budget.rootCeiling = budget.nodes + (limits.nodes - budget.nodes) / remainingRoots--;
            if (!budget.expand()) { results.addAll(limited(base.copy(), item, remaining, "Expanded-node budget reached", budget)); break; }
            State branch = base.copy();
            if (depth == 0) branch.root = route.id();
            var output = route.output();
            if (!route.dependencySupported() || output == null || !output.fixed() || output.hasNonDefaultComponents()) {
                branch.issues.add(new PlanResult.Issue(item, remaining, "unsupported_recipe", route.id() + ": " + String.join("; ", route.limitations())));
                branch.steps.add(new PlanResult.Step(route.id(), item, remaining, 0, route.type(), depth, route.limitations()));
                results.add(branch);
                continue;
            }
            long crafts = (remaining + output.count() - 1) / output.count();
            if (crafts > MAX_QUANTITY || route.ingredients().size() > 64) {
                results.addAll(limited(branch, item, remaining, "Recipe multiplication exceeds quantity/ingredient budget", budget));
                continue;
            }
            int inheritedIssues = branch.issues.size();
            int allocationId = branch.nextAllocation++;
            branch.allocations.put(allocationId, new ArrayList<>());
            List<State> partials = List.of(branch);
            // Constrained positions first prevents spending an exact input on an avoidable tag choice.
            var requirements = route.ingredients().stream().sorted(Comparator
                    .comparingInt((NormalizedRecipe.Requirement r) -> r.alternatives().size())
                    .thenComparingInt(NormalizedRecipe.Requirement::position)).toList();
            for (var requirement : requirements) {
                long required;
                try { required = Math.multiplyExact(crafts, requirement.count()); }
                catch (ArithmeticException exception) { required = MAX_QUANTITY + 1; }
                List<State> expanded = new ArrayList<>();
                for (State partial : partials) {
                    if (required > MAX_QUANTITY) expanded.addAll(limited(partial.copy(), item, required, "Ingredient quantity exceeds planning budget", budget));
                    else expanded.addAll(require(requirement, required, partial, path, depth + 1, budget, allocationId));
                }
                partials = trim(expanded, budget);
            }
            long produced = crafts * output.count();
            for (State partial : partials) {
                var allocated = partial.allocations.remove(allocationId);
                partial.steps.add(new PlanResult.Step(route.id(), item, produced, crafts, route.type(), depth, route.limitations(),
                        allocated == null ? List.of() : compact(allocated)));
                // Known shortages may be acquired later; opaque/cyclic/limited steps cannot generate usable credit.
                if (partial.issues.size() == inheritedIssues && produced > remaining) add(partial.planned, item, produced - remaining);
                results.add(partial);
            }
        }
        if (depth == 0) budget.rootCeiling = limits.nodes;
        return trim(results, budget);
    }

    private List<State> require(NormalizedRecipe.Requirement requirement, long amount, State input,
                                Set<String> path, int depth, Budget budget, int allocationId) {
        if (!requirement.supported() || requirement.alternatives().isEmpty()) {
            State result = input.copy();
            result.issues.add(new PlanResult.Issue(String.join("|", requirement.sourceTags()), amount, "unsupported_ingredient", requirement.detail()));
            return List.of(result);
        }
        if (!requirement.alternativesComplete()) budget.truncated = true;
        List<String> options = requirement.alternatives().stream().distinct().sorted(Comparator
                .comparingLong((String item) -> -(input.original.getOrDefault(item, 0L) + input.planned.getOrDefault(item, 0L)))
                .thenComparing(Comparator.naturalOrder())).toList();
        if (options.size() > limits.alternatives) budget.truncated = true;
        List<State> candidates = new ArrayList<>();
        for (String preferred : options.stream().limit(limits.alternatives).toList()) {
            if (!budget.expand()) { candidates.addAll(limited(input.copy(), preferred, amount, "Alternative expansion budget reached", budget)); break; }
            State state = input.copy();
            long taken = take(state, preferred, amount);
            allocate(state, allocationId, requirement.position(), preferred, taken);
            long left = amount - taken;
            for (String option : options) {
                if (left == 0) break;
                if (!option.equals(preferred)) {
                    taken = take(state, option, left);
                    allocate(state, allocationId, requirement.position(), option, taken);
                    left -= taken;
                }
            }
            if (left == 0) candidates.add(state);
            else {
                for (State resolved : resolve(preferred, left, state, path, depth, budget)) {
                    allocate(resolved, allocationId, requirement.position(), preferred, left);
                    candidates.add(resolved);
                }
            }
        }
        // A tag demand can be manufactured from several members. Unit expansion is finite;
        // whole-member batching above remains the fallback when this additional search is capped.
        if (amount > 1 && options.size() > 1 && budget.nodes < budget.rootCeiling) {
            List<Manufacturing> frontier = List.of(new Manufacturing(input.copy(), amount));
            while (frontier.stream().anyMatch(f -> f.remaining > 0) && budget.nodes < budget.rootCeiling) {
                List<Manufacturing> expanded = new ArrayList<>();
                for (Manufacturing entry : frontier) {
                    if (entry.remaining == 0) { expanded.add(entry); continue; }
                    for (String option : options.stream().limit(limits.alternatives).toList()) {
                        if (!budget.expand()) break;
                        for (State state : resolve(option, 1, entry.state, path, depth, budget)) {
                            allocate(state, allocationId, requirement.position(), option, 1);
                            expanded.add(new Manufacturing(state, entry.remaining - 1));
                        }
                    }
                }
                if (expanded.isEmpty()) break;
                long remaining = expanded.stream().mapToLong(Manufacturing::remaining).min().orElse(0);
                List<State> states = trim(expanded.stream().filter(f -> f.remaining == remaining).map(Manufacturing::state).toList(), budget);
                frontier = states.stream().map(s -> new Manufacturing(s, remaining)).toList();
                if (remaining == 0) { candidates.addAll(states); break; }
            }
            if (frontier.stream().anyMatch(f -> f.remaining > 0)) budget.truncated = true;
        } else if (amount > 1 && options.size() > 1) budget.truncated = true;
        return trim(candidates, budget);
    }
    private record Manufacturing(State state, long remaining) {}
    private static void allocate(State state, int allocationId, int position, String item, long amount) {
        if (amount > 0) state.allocations.computeIfAbsent(allocationId, unused -> new ArrayList<>())
                .add(new PlanResult.AllocatedIngredient(position, item, amount));
    }
    private static List<PlanResult.AllocatedIngredient> compact(List<PlanResult.AllocatedIngredient> ingredients) {
        Map<Integer, Map<String, Long>> grouped = new TreeMap<>();
        for (var ingredient : ingredients) grouped.computeIfAbsent(ingredient.position(), unused -> new TreeMap<>())
                .merge(ingredient.item(), ingredient.quantity(), Math::addExact);
        List<PlanResult.AllocatedIngredient> result = new ArrayList<>();
        grouped.forEach((position, counts) -> counts.forEach((item, count) -> result.add(new PlanResult.AllocatedIngredient(position, item, count))));
        return List.copyOf(result);
    }

    private static long take(State state, String item, long amount) {
        long original = Math.min(amount, state.original.getOrDefault(item, 0L));
        if (original > 0) {
            subtract(state.original, item, original);
            add(state.usedOriginal, item, original);
        }
        long planned = Math.min(amount - original, state.planned.getOrDefault(item, 0L));
        if (planned > 0) subtract(state.planned, item, planned);
        return original + planned;
    }
    private static void subtract(Map<String, Long> map, String key, long amount) {
        long value = map.getOrDefault(key, 0L) - amount;
        if (value == 0) map.remove(key); else map.put(key, value);
    }
    private static void add(Map<String, Long> map, String key, long value) { map.merge(key, value, Math::addExact); }
    private static long sum(Map<String, Long> map) { return map.values().stream().mapToLong(Long::longValue).sum(); }
    private static List<PlanResult.Resource> resources(Map<String, Long> map) {
        return map.entrySet().stream().map(e -> new PlanResult.Resource(e.getKey(), e.getValue())).toList();
    }
    private List<State> limited(State state, String item, long amount, String reason, Budget budget) {
        budget.truncated = true;
        if (state.issues.size() < 128) state.issues.add(new PlanResult.Issue(item, amount, "search_limit", reason));
        return List.of(state);
    }
    private List<State> trim(List<State> states, Budget budget) {
        if (states.isEmpty()) throw new IllegalStateException("Planner produced no candidate state");
        // Tie-breaking uses full sorted resource ledgers, avoiding registry/hash iteration dependence.
        Comparator<State> score = Comparator.comparingInt((State s) -> s.issues.size())
                .thenComparingLong(s -> sum(s.missing)).thenComparingInt(s -> s.depth)
                .thenComparingInt(s -> s.steps.size()).thenComparingLong(s -> -sum(s.usedOriginal))
                .thenComparing(DeterministicPlanner::signature);
        Map<String, State> unique = new LinkedHashMap<>();
        states.stream().sorted(score).forEach(s -> unique.putIfAbsent(signature(s), s));
        if (unique.size() > limits.beamWidth) budget.truncated = true;
        List<State> retained = new ArrayList<>();
        Set<String> roots = new LinkedHashSet<>();
        for (State state : unique.values()) if (roots.add(rootRecipe(state)) && retained.size() < limits.beamWidth) retained.add(state);
        for (State state : unique.values()) if (retained.size() < limits.beamWidth && !retained.contains(state)) retained.add(state);
        return retained.stream().sorted(score).toList();
    }
    private static String signature(State state) {
        return state.root + "|" + state.steps.stream().map(s -> s.recipeId() + s.ingredients()).toList() + "|" + new TreeMap<>(state.original)
                + "|" + new TreeMap<>(state.planned) + "|" + new TreeMap<>(state.missing) + "|" + state.issues + "|" + state.allocations;
    }
    private static String rootRecipe(State state) { return state.root; }
    private static PlanResult.Action next(String goal, long amount, State state, boolean owned) {
        if (owned) return new PlanResult.Action("complete", goal, amount, "", "The requested quantity is already present in the inspected main inventory.");
        if (!state.issues.isEmpty()) {
            var issue = state.issues.getFirst();
            return new PlanResult.Action("inspect", issue.item(), issue.quantity(), "", issue.reason());
        }
        if (!state.missing.isEmpty()) {
            var first = state.missing.entrySet().iterator().next();
            return new PlanResult.Action("obtain", first.getKey(), first.getValue(), "",
                    "First unresolved material on the selected production path. No indexed supported route was found for this leaf; gathering methods are not modeled.");
        }
        if (!state.steps.isEmpty()) {
            var step = state.steps.getFirst();
            return new PlanResult.Action("prepare_recipe", step.output(), step.outputQuantity(), step.recipeId(),
                    "The selected path's first material step has inputs reserved. Verify execution conditions before processing: " + String.join("; ", step.limitations()));
        }
        return new PlanResult.Action("inspect", goal, amount, "", "No actionable supported path was established.");
    }
    private static void validateItem(String item) {
        if (item == null || item.length() > 256 || !item.matches("[a-z0-9_.-]+:[a-z0-9/._-]+")) throw new IllegalArgumentException("Expected bounded namespaced item ID");
    }
    private static void checkQuantity(long quantity) {
        if (quantity < 1 || quantity > MAX_QUANTITY) throw new IllegalArgumentException("Goal quantity outside safe bounds");
    }
    private static final class State {
        final Map<String, Long> original = new TreeMap<>();
        final Map<String, Long> planned = new TreeMap<>();
        final Map<String, Long> usedOriginal = new TreeMap<>();
        final Map<String, Long> missing = new LinkedHashMap<>();
        final List<PlanResult.Step> steps = new ArrayList<>();
        final List<PlanResult.Issue> issues = new ArrayList<>();
        final Map<Integer, List<PlanResult.AllocatedIngredient>> allocations = new TreeMap<>();
        int nextAllocation;
        String root = "";
        int depth;
        State copy() {
            State copy = new State();
            copy.original.putAll(original); copy.planned.putAll(planned); copy.usedOriginal.putAll(usedOriginal);
            copy.missing.putAll(missing); copy.steps.addAll(steps); copy.issues.addAll(issues); copy.depth = depth;
            allocations.forEach((key, value) -> copy.allocations.put(key, new ArrayList<>(value)));
            copy.nextAllocation = nextAllocation; copy.root = root;
            return copy;
        }
    }
    private final class Budget {
        final RecipeIndex index;
        int nodes;
        boolean truncated;
        int rootCeiling = limits.nodes;
        Budget(RecipeIndex index) { this.index = index; }
        boolean expand() { if (nodes >= rootCeiling || nodes >= limits.nodes) { truncated = true; return false; } nodes++; return true; }
    }
}
