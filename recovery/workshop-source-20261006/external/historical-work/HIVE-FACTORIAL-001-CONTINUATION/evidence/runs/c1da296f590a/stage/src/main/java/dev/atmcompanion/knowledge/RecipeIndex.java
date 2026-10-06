package dev.atmcompanion.knowledge;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

/** Immutable index detached from Minecraft; deterministic routes with explicit global and per-output coverage. */
public final class RecipeIndex {
    public static final int SCHEMA_VERSION = 2;
    public static final int MAX_RECIPES = 50_000;
    public static final int MAX_ROUTES_PER_OUTPUT = 32;
    public static final int MAX_TOTAL_ALTERNATIVES = 200_000;
    public static final int MAX_TOTAL_IDENTITIES = 400_000;
    private final int schemaVersion;
    private final long generation;
    private final String builtAt;
    private final Map<String, NormalizedRecipe> recipesById;
    private final Map<String, List<NormalizedRecipe>> recipesByOutput;
    private final Map<String, Integer> outputRecipeCounts;
    private final Stats stats;
    private final Coverage coverage;
    private final boolean complete;

    /** Synchronous pure-data constructor retained for small fixtures and imported in-memory models. */
    public RecipeIndex(int schemaVersion, long generation, String builtAt, List<NormalizedRecipe> recipes, Stats stats) {
        this(schemaVersion, generation, builtAt, assemble(recipes), stats, null);
    }
    private static Assembly assemble(List<NormalizedRecipe> recipes) {
        if (recipes.size() > MAX_RECIPES) throw new IllegalArgumentException("Index recipe count exceeds bound");
        Assembly assembly = new Assembly();
        recipes.forEach(assembly::add);
        while (assembly.freezeNext()) { }
        return assembly;
    }
    RecipeIndex(int schemaVersion, long generation, String builtAt, Assembly assembly, Stats stats, Coverage coverage) {
        if ((schemaVersion != 1 && schemaVersion != SCHEMA_VERSION) || generation < 0) throw new IllegalArgumentException("Invalid recipe index schema/generation");
        Instant.parse(Objects.requireNonNull(builtAt));
        this.schemaVersion = schemaVersion; this.generation = generation; this.builtAt = builtAt;
        this.stats = Objects.requireNonNull(stats);
        if (!assembly.frozen || assembly.claimed || assembly.byId.size() != stats.indexedRecipes()) throw new IllegalArgumentException("Index assembly incomplete/count mismatch");
        assembly.claimed = true;
        // Assembly relinquishes ownership. No bulk copying or sorting occurs at publication.
        recipesById = Collections.unmodifiableMap(assembly.byId);
        recipesByOutput = Collections.unmodifiableMap(assembly.byOutput);
        outputRecipeCounts = Collections.unmodifiableMap(assembly.counts);
        complete = !stats.definitionsTruncated() && stats.unknownOutputs() == 0
                && stats.inspectedRecipes() == stats.indexedRecipes() && assembly.allOutputsFixed;
        this.coverage = coverage == null ? new Coverage(defaultReasons(stats, assembly.truncatedOutputs), 0,
                assembly.alternatives, assembly.identities, assembly.truncatedOutputs, 0, 0, 0) : coverage;
    }
    private static List<String> defaultReasons(Stats stats, int truncatedOutputs) {
        List<String> reasons = new ArrayList<>();
        if (stats.definitionsTruncated()) reasons.add("definitions_truncated");
        if (stats.unknownOutputs() > 0) reasons.add("unknown_or_nonfixed_outputs");
        if (stats.unsupportedRecipes() > 0) reasons.add("unsupported_dependencies");
        if (truncatedOutputs > 0) reasons.add("output_route_cap");
        return reasons;
    }
    public int schemaVersion() { return schemaVersion; }
    public long generation() { return generation; }
    public String builtAt() { return builtAt; }
    public Stats stats() { return stats; }
    public Coverage coverage() { return coverage; }
    public Map<String, NormalizedRecipe> recipesById() { return recipesById; }
    public Map<String, List<NormalizedRecipe>> recipesByOutput() { return recipesByOutput; }
    public Map<String, Integer> outputRecipeCounts() { return outputRecipeCounts; }
    public List<NormalizedRecipe> recipesFor(String item) { return recipesByOutput.getOrDefault(item, List.of()); }
    public boolean recipesForTruncated(String item) { return outputRecipeCounts.getOrDefault(item, 0) > recipesFor(item).size(); }
    /** Full static-output coverage only; unsupported ingredient/execution semantics remain per-recipe unknown. */
    public boolean complete() { return complete; }
    RecipeIndex withMeasurements(long elapsedMillis, long slices, long activeMillis, long maxSliceMillis) {
        return new RecipeIndex(this, new Stats(stats.totalRecipes(), stats.inspectedRecipes(), stats.indexedRecipes(),
                stats.unknownOutputs(), stats.unsupportedRecipes(), stats.definitionsTruncated(), elapsedMillis),
                new Coverage(coverage.reasons(), coverage.invalidIdentities(), coverage.retainedAlternatives(),
                        coverage.retainedIdentities(), coverage.truncatedOutputs(), slices, activeMillis, maxSliceMillis));
    }
    private RecipeIndex(RecipeIndex source, Stats measuredStats, Coverage measuredCoverage) {
        schemaVersion = source.schemaVersion; generation = source.generation; builtAt = source.builtAt;
        recipesById = source.recipesById; recipesByOutput = source.recipesByOutput; outputRecipeCounts = source.outputRecipeCounts;
        stats = measuredStats; coverage = measuredCoverage; complete = source.complete;
    }
    /** Owns mutable lookup construction until one final index claims it. Each step is bounded. */
    static final class Assembly {
        private static final Comparator<NormalizedRecipe> ROUTE_ORDER = Comparator
                .comparing((NormalizedRecipe recipe) -> !recipe.dependencySupported()).thenComparing(NormalizedRecipe::id);
        private final TreeMap<String, NormalizedRecipe> byId = new TreeMap<>();
        private final TreeMap<String, List<NormalizedRecipe>> byOutput = new TreeMap<>();
        private final TreeMap<String, Integer> counts = new TreeMap<>();
        private Iterator<Map.Entry<String, List<NormalizedRecipe>>> freezing;
        private int alternatives;
        private int identities;
        private int truncatedOutputs;
        private boolean allOutputsFixed = true;
        private boolean frozen;
        private boolean claimed;
        void add(NormalizedRecipe recipe) {
            if (freezing != null || frozen || claimed || byId.size() >= MAX_RECIPES) throw new IllegalStateException("Index assembly closed or full");
            if (byId.putIfAbsent(recipe.id(), recipe) != null) throw new IllegalArgumentException("Duplicate recipe ID " + recipe.id());
            for (var requirement : recipe.ingredients()) {
                alternatives += requirement.alternatives().size();
                identities += requirement.alternatives().size() + requirement.sourceItems().size() + requirement.sourceTags().size();
            }
            if (alternatives > MAX_TOTAL_ALTERNATIVES) throw new IllegalArgumentException("Global ingredient alternative bound exceeded");
            if (identities > MAX_TOTAL_IDENTITIES) throw new IllegalArgumentException("Global ingredient source/resolved identity bound exceeded");
            if (recipe.output() == null || !recipe.output().fixed()) allOutputsFixed = false;
            if (recipe.output() == null) return;
            String item = recipe.output().item();
            int count = counts.merge(item, 1, Integer::sum);
            if (count == MAX_ROUTES_PER_OUTPUT + 1) truncatedOutputs++;
            List<NormalizedRecipe> routes = byOutput.computeIfAbsent(item, ignored -> new ArrayList<>());
            int position = Collections.binarySearch(routes, recipe, ROUTE_ORDER);
            if (position < 0) position = -position - 1;
            if (position < MAX_ROUTES_PER_OUTPUT) {
                routes.add(position, recipe);
                if (routes.size() > MAX_ROUTES_PER_OUTPUT) routes.removeLast();
            }
        }
        boolean freezeNext() {
            if (claimed) throw new IllegalStateException("Index assembly already published");
            if (frozen) return false;
            if (freezing == null) freezing = byOutput.entrySet().iterator();
            if (!freezing.hasNext()) { frozen = true; return false; }
            var entry = freezing.next();
            entry.setValue(List.copyOf(entry.getValue()));
            return true;
        }
        int truncatedOutputs() { return truncatedOutputs; }
    }
    public record Coverage(List<String> reasons, int invalidIdentities, int retainedAlternatives, int retainedIdentities,
                           int truncatedOutputs, long slices, long activeMillis, long maxSliceMillis) {
        public Coverage {
            reasons = List.copyOf(reasons);
            if (reasons.size() > 32 || invalidIdentities < 0 || retainedAlternatives < 0 || retainedAlternatives > MAX_TOTAL_ALTERNATIVES
                    || retainedIdentities < 0 || retainedIdentities > MAX_TOTAL_IDENTITIES || truncatedOutputs < 0
                    || slices < 0 || activeMillis < 0 || maxSliceMillis < 0) throw new IllegalArgumentException("Invalid index coverage");
        }
    }
    public record Stats(int totalRecipes, int inspectedRecipes, int indexedRecipes, int unknownOutputs,
                        int unsupportedRecipes, boolean definitionsTruncated, long buildMillis) {
        public Stats {
            if (totalRecipes < 0 || inspectedRecipes < 0 || indexedRecipes < 0 || unknownOutputs < 0 || unsupportedRecipes < 0
                    || buildMillis < 0 || inspectedRecipes > totalRecipes || indexedRecipes > inspectedRecipes
                    || unknownOutputs > indexedRecipes || unsupportedRecipes > indexedRecipes
                    || (!definitionsTruncated && inspectedRecipes != totalRecipes)) throw new IllegalArgumentException("Invalid recipe index statistics");
        }
    }
}
