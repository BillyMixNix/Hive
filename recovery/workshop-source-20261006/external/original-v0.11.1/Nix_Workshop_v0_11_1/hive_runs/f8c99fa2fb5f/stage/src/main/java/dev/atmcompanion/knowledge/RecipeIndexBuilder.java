package dev.atmcompanion.knowledge;

import com.mojang.logging.LogUtils;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Collection;
import java.util.Iterator;
import java.util.List;
import java.util.Objects;
import java.util.TreeMap;
import java.util.TreeSet;
import net.minecraft.core.HolderLookup;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.MinecraftServer;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.BlastingRecipe;
import net.minecraft.world.item.crafting.AbstractCookingRecipe;
import net.minecraft.world.item.crafting.CampfireCookingRecipe;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.ShapedRecipe;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import net.minecraft.world.item.crafting.SmeltingRecipe;
import net.minecraft.world.item.crafting.SmokingRecipe;
import org.slf4j.Logger;

/** Logical-server extraction only; resulting index retains no recipe, registry, ItemStack or world objects. */
public final class RecipeIndexBuilder {
    public static final long MAX_SLICE_NANOS = 5_000_000L;
    public static final int SELECTION_OPERATIONS_PER_SLICE = 512;
    public static final int NORMALIZATION_OPERATIONS_PER_SLICE = 128;
    public static final int LOOKUP_OPERATIONS_PER_SLICE = 512;
    public static final int MAX_DEFINITIONS_SELECTED = 100_000;
    public static final int MAX_TAG_MEMBERS_SCANNED = 4096;
    private static final Logger LOGGER = LogUtils.getLogger();
    private RecipeIndexBuilder() {}

    public static RecipeIndex build(MinecraftServer server, long generation) {
        return build(server, generation, server.getRecipeManager().getRecipes());
    }
    /** Synchronous harness seam; production lifecycle advances the same job one slice per server tick. */
    public static RecipeIndex build(MinecraftServer server, long generation, Collection<? extends RecipeHolder<?>> all) {
        Job job = start(server, generation, all);
        while (!job.done()) job.advance();
        return job.result();
    }

    public static Job start(MinecraftServer server, long generation, Collection<? extends RecipeHolder<?>> all) {
        requireThread(server);
        return new Job(server, generation, all);
    }
    private static void requireThread(MinecraftServer server) {
        if (server == null || !server.isSameThread()) throw new IllegalStateException("Recipe indexing requires the logical server thread");
    }
    public record Progress(String phase, int totalDefinitions, int visitedDefinitions, int selectedDefinitions,
                           int normalizedDefinitions, int lookupDefinitions, long slices, long activeMillis,
                           long elapsedMillis, long maxSliceMillis) { }

    /** Finite logical-server job. Time only schedules work; it never discards otherwise selected recipes. */
    public static final class Job {
        private final MinecraftServer server;
        private final long generation;
        private final long started = System.nanoTime();
        private final int total;
        private Iterator<? extends RecipeHolder<?>> source;
        private final TreeMap<RecipeSelection, RecipeHolder<?>> selected = new TreeMap<>();
        private Iterator<RecipeHolder<?>> normalizing;
        private final List<NormalizedRecipe> recipes = new ArrayList<>();
        private final RecipeIndex.Assembly assembly = new RecipeIndex.Assembly();
        private final Budget budget = new Budget();
        private String phase = "selecting";
        private int visited;
        private int invalidIdentities;
        private int unknownOutputs;
        private int unsupported;
        private int lookup;
        private long slices;
        private long activeNanos;
        private long maxSliceNanos;
        private RecipeIndex result;
        private Job(MinecraftServer server, long generation, Collection<? extends RecipeHolder<?>> all) {
            if (generation < 0) throw new IllegalArgumentException("Invalid generation");
            this.server = server; this.generation = generation;
            total = Objects.requireNonNull(all).size();
            source = all.iterator();
        }
        public void advance() { advance(MAX_SLICE_NANOS); }
        /** A smaller slice is useful for verifying that scheduling cannot alter the resulting facts. */
        public void advance(long sliceNanos) {
            requireThread(server);
            if (sliceNanos < 1 || sliceNanos > MAX_SLICE_NANOS) throw new IllegalArgumentException("Invalid slice budget");
            if (done()) return;
            long began = System.nanoTime();
            try {
                int limit = phase.equals("selecting") ? SELECTION_OPERATIONS_PER_SLICE
                        : phase.equals("normalizing") ? NORMALIZATION_OPERATIONS_PER_SLICE : LOOKUP_OPERATIONS_PER_SLICE;
                String originalPhase = phase;
                int operations = 0;
                do {
                    step();
                    operations++;
                } while (!done() && phase.equals(originalPhase) && operations < limit && System.nanoTime() - began < sliceNanos);
            } finally {
                long duration = System.nanoTime() - began;
                slices++; activeNanos += duration; maxSliceNanos = Math.max(maxSliceNanos, duration);
            }
            if (done()) {
                result = result.withMeasurements((System.nanoTime() - started) / 1_000_000L,
                        slices, activeNanos / 1_000_000L, maxSliceNanos / 1_000_000L);
                LOGGER.info("ATM Companion indexed {}/{} recipe definitions across {} output items ({} unknown/nonfixed outputs, {} unsupported dependencies, {} retained alternatives, {} retained identities, {} active ms, {} elapsed ms, {} slices, {} max slice ms, generation {})",
                        recipes.size(), total, result.recipesByOutput().size(), unknownOutputs, unsupported,
                        budget.retained.alternativesUsed(), budget.retained.identitiesUsed(), result.coverage().activeMillis(),
                        result.stats().buildMillis(), slices, result.coverage().maxSliceMillis(), generation);
            }
        }
        private void step() {
            switch (phase) {
                case "selecting" -> {
                    if (visited >= MAX_DEFINITIONS_SELECTED || !source.hasNext()) {
                        source = null;
                        normalizing = selected.values().iterator();
                        phase = "normalizing";
                        return;
                    }
                    RecipeHolder<?> holder = source.next(); visited++;
                    if (!bounded(holder.id())) { invalidIdentities++; return; }
                    selected.put(selectionRank(holder), holder);
                    if (selected.size() > RecipeIndex.MAX_RECIPES) selected.pollLastEntry();
                }
                case "normalizing" -> {
                    if (!normalizing.hasNext()) { normalizing = null; phase = "lookups"; return; }
                    RecipeHolder<?> holder = normalizing.next();
                    NormalizedRecipe normalized;
                    try { normalized = normalize(holder, server.registryAccess(), budget); }
                    catch (RuntimeException | LinkageError exception) {
                        if (budget.failures++ < 3) LOGGER.warn("ATM Companion index could not extract recipe {}", holder.id(), exception);
                        normalized = new NormalizedRecipe(holder.id().toString(), "unavailable", "unavailable", null,
                                List.of(), "unsupported", false, List.of("Extraction failed: " + exception.getClass().getSimpleName() + "; see server log"));
                    }
                    recipes.add(normalized);
                    if (normalized.output() == null || !normalized.output().fixed()) unknownOutputs++;
                    if (!normalized.dependencySupported()) unsupported++;
                }
                case "lookups" -> {
                    if (lookup >= recipes.size()) { phase = "freezing"; return; }
                    assembly.add(recipes.get(lookup++));
                }
                case "freezing" -> { if (!assembly.freezeNext()) finish(); }
                default -> throw new IllegalStateException("Unexpected recipe index phase " + phase);
            }
        }
        private void finish() {
            List<String> reasons = new ArrayList<>();
            if (total > MAX_DEFINITIONS_SELECTED) reasons.add("definition_scan_cap");
            if (visited - invalidIdentities > RecipeIndex.MAX_RECIPES) reasons.add("retained_definition_cap");
            if (invalidIdentities > 0) reasons.add("invalid_recipe_identity");
            if (unknownOutputs > 0) reasons.add("unknown_or_nonfixed_outputs");
            if (unsupported > 0) reasons.add("unsupported_dependencies");
            if (budget.retentionLimited > 0) reasons.add("ingredient_retention_budget");
            if (assembly.truncatedOutputs() > 0) reasons.add("output_route_cap");
            var stats = new RecipeIndex.Stats(total, recipes.size(), recipes.size(), unknownOutputs, unsupported,
                    total > recipes.size(), 0);
            var coverage = new RecipeIndex.Coverage(reasons, invalidIdentities, budget.retained.alternativesUsed(),
                    budget.retained.identitiesUsed(), assembly.truncatedOutputs(), 0, 0, 0);
            result = new RecipeIndex(RecipeIndex.SCHEMA_VERSION, generation, Instant.now().toString(), assembly, stats, coverage);
            phase = "complete";
        }
        public boolean done() { return result != null; }
        public RecipeIndex result() {
            requireThread(server);
            if (!done()) throw new IllegalStateException("Recipe index build has not completed");
            return result;
        }
        public Progress progress() {
            requireThread(server);
            return new Progress(phase, total, visited, selected.size(), recipes.size(), lookup, slices,
                    activeNanos / 1_000_000L, (System.nanoTime() - started) / 1_000_000L, maxSliceNanos / 1_000_000L);
        }
    }

    /** Also usable by runtime tests for synthetic real recipe objects; no live object is retained. */
    public static NormalizedRecipe normalize(RecipeHolder<?> holder, HolderLookup.Provider registries) {
        return normalize(holder, registries, new Budget());
    }
    private static NormalizedRecipe normalize(RecipeHolder<?> holder, HolderLookup.Provider registries, Budget budget) {
        Recipe<?> recipe = holder.value();
        var typeKey = BuiltInRegistries.RECIPE_TYPE.getKey(recipe.getType());
        var serializerKey = BuiltInRegistries.RECIPE_SERIALIZER.getKey(recipe.getSerializer());
        boolean identitiesKnown = bounded(typeKey) && bounded(serializerKey);
        String type = bounded(typeKey) ? typeKey.toString() : "unavailable";
        String serializer = bounded(serializerKey) ? serializerKey.toString() : "unavailable";
        boolean crafting = recipe.getClass() == ShapedRecipe.class || recipe.getClass() == ShapelessRecipe.class;
        boolean cooking = recipe.getClass() == SmeltingRecipe.class || recipe.getClass() == BlastingRecipe.class
                || recipe.getClass() == SmokingRecipe.class || recipe.getClass() == CampfireCookingRecipe.class;
        boolean fixed = (crafting || cooking) && !recipe.isSpecial();
        String kind = crafting ? "crafting" : cooking ? "cooking" : "unsupported";
        var execution = executionRequirement(recipe);
        List<String> limitations = new ArrayList<>();
        ItemStack preview = null;
        try { preview = recipe.getResultItem(registries); }
        catch (RuntimeException | LinkageError exception) {
            if (budget.failures++ < 3) LOGGER.warn("ATM Companion index could not extract output of recipe {}", holder.id(), exception);
            limitations.add("Output extraction failed: " + exception.getClass().getSimpleName() + "; see server log");
        }
        boolean outputKnown = preview != null && !preview.isEmpty() && bounded(BuiltInRegistries.ITEM.getKey(preview.getItem()));
        if (preview != null && !preview.isEmpty() && !outputKnown) limitations.add("Output registry identity exceeds retained-ID bounds");
        NormalizedRecipe.Output output = !outputKnown ? null : new NormalizedRecipe.Output(
                BuiltInRegistries.ITEM.getKey(preview.getItem()).toString(), preview.getCount(), fixed,
                !preview.getComponentsPatch().isEmpty());
        if (output == null) limitations.add("No item output preview exposed; dynamic, fluid or other outputs are unknown");
        if (!fixed) limitations.add("Unrecognized or dynamic recipe class: advertised output is a preview, never guaranteed fixed output");
        if (output != null && output.hasNonDefaultComponents()) limitations.add("Output has nondefault components; component values and compatibility are unsupported");
        if (!identitiesKnown) limitations.add("Recipe type or serializer registry identity unavailable or exceeds bounds");
        if (!fixed || output == null || output.hasNonDefaultComponents() || !identitiesKnown) {
            return new NormalizedRecipe(holder.id().toString(), type, serializer, output, List.of(), kind, false, limitations, execution);
        }

        var inputs = recipe.getIngredients();
        List<NormalizedRecipe.Requirement> ingredients = new ArrayList<>();
        int maximumInputs = crafting ? 9 : 1;
        if (inputs.size() > maximumInputs) {
            limitations.add("Input shape exceeds the verified vanilla recipe class bounds");
            return new NormalizedRecipe(holder.id().toString(), type, serializer, output, List.of(), kind, false, limitations, execution);
        }
        for (int position = 0; position < inputs.size(); position++) {
            Ingredient ingredient = inputs.get(position);
            if (!ingredient.isCustom() && ingredient.isEmpty()) continue;
            ingredients.add(normalizeIngredient(position, ingredient));
        }
        boolean rawSupported = !ingredients.isEmpty() && ingredients.stream().allMatch(NormalizedRecipe.Requirement::supported);
        ingredients = ingredients.stream().map(requirement -> budget.retained.retain(requirement, rawSupported)).toList();
        if (rawSupported && ingredients.stream().anyMatch(requirement -> !requirement.supported())) budget.retentionLimited++;
        limitations.add("Materials only: no crafting access, recipe-unlock, dimension or execution capability has been verified");
        limitations.add("Input containers/remainders are not credited; dependencies conservatively consume ingredients");
        if (cooking) limitations.add("Cooking device, fuel/heat, processing time, power and current machine state are unknown");
        if (ingredients.isEmpty()) limitations.add("No supported material requirements exposed");
        if (ingredients.stream().anyMatch(requirement -> !requirement.supported())) limitations.add("Some ingredient semantics or alternatives are unsupported/incomplete");
        boolean supported = output != null && !output.hasNonDefaultComponents() && identitiesKnown
                && !ingredients.isEmpty() && ingredients.stream().allMatch(NormalizedRecipe.Requirement::supported);
        return new NormalizedRecipe(holder.id().toString(), type, serializer, output, ingredients, kind, supported, limitations, execution);
    }
    private static NormalizedRecipe.ExecutionRequirement executionRequirement(Recipe<?> recipe) {
        Class<?> type = recipe.getClass();
        if (type == ShapedRecipe.class || type == ShapelessRecipe.class) {
            int width = recipe instanceof ShapedRecipe shaped ? shaped.getWidth() : 0;
            int height = recipe instanceof ShapedRecipe shaped ? shaped.getHeight() : 0;
            if (width > 3 || height > 3) return NormalizedRecipe.ExecutionRequirement.unknown();
            return new NormalizedRecipe.ExecutionRequirement("crafting", recipe.canCraftInDimensions(2, 2),
                    recipe.canCraftInDimensions(3, 3), width, height, 0);
        }
        String kind = type == SmeltingRecipe.class ? "smelting" : type == BlastingRecipe.class ? "blasting"
                : type == SmokingRecipe.class ? "smoking" : type == CampfireCookingRecipe.class ? "campfire" : "unknown";
        if (kind.equals("unknown")) return NormalizedRecipe.ExecutionRequirement.unknown();
        int ticks = ((AbstractCookingRecipe) recipe).getCookingTime();
        if (ticks < 0) return NormalizedRecipe.ExecutionRequirement.unknown();
        return new NormalizedRecipe.ExecutionRequirement(kind, false, false, 0, 0, ticks);
    }
    private static NormalizedRecipe.Requirement normalizeIngredient(int position, Ingredient ingredient) {
        if (ingredient.isCustom()) return unsupported(position, "Custom ingredient, including component/fluid/predicate semantics, is not flattened");
        if (!ingredient.isSimple()) return unsupported(position, "Component-sensitive ingredient is unsupported");
        Ingredient.Value[] values = ingredient.getValues();
        if (values.length > NormalizedRecipe.MAX_SOURCE_VALUES) return unsupported(position, "Source ingredient alternatives exceed bound");
        TreeSet<String> items = new TreeSet<>();
        TreeSet<String> tags = new TreeSet<>();
        TreeSet<String> alternatives = new TreeSet<>();
        boolean complete = true;
        boolean emptyTag = false;
        int available = NormalizedRecipe.MAX_ALTERNATIVES;
        for (Ingredient.Value value : values) {
            if (value instanceof Ingredient.ItemValue item) {
                if (item.item().isEmpty()) return unsupported(position, "Empty/air item value cannot be represented as a consumed material");
                if (!bounded(BuiltInRegistries.ITEM.getKey(item.item().getItem()))) return unsupported(position, "Source item identity exceeds bounds");
                String id = BuiltInRegistries.ITEM.getKey(item.item().getItem()).toString();
                items.add(id);
                alternatives.add(id);
                if (alternatives.size() > available) { alternatives.pollLast(); complete = false; }
            } else if (value instanceof Ingredient.TagValue tag) {
                if (!bounded(tag.tag().location())) return unsupported(position, "Source tag identity exceeds bounds");
                tags.add(tag.tag().location().toString());
                var members = BuiltInRegistries.ITEM.getTag(tag.tag());
                if (members.isEmpty() || members.get().size() == 0) { emptyTag = true; continue; }
                // An oversized tag cannot become a supported requirement. Keep its identity, not an unusable prefix.
                if (members.get().size() > available) { complete = false; continue; }
                int visited = 0;
                for (var member : members.get()) {
                    if (visited++ >= MAX_TAG_MEMBERS_SCANNED) { complete = false; break; }
                    if (!bounded(BuiltInRegistries.ITEM.getKey(member.value()))) { complete = false; continue; }
                    alternatives.add(BuiltInRegistries.ITEM.getKey(member.value()).toString());
                    if (alternatives.size() > available) { alternatives.pollLast(); complete = false; }
                }
            } else return unsupported(position, "Unrecognized original ingredient value");
        }
        String kind = emptyTag ? "unsupported_empty_tag" : values.length == 1 && tags.size() == 1 ? "tag"
                : values.length == 1 && items.size() == 1 ? "exact" : "alternatives";
        return new NormalizedRecipe.Requirement(position, 1, kind, List.copyOf(items), List.copyOf(tags), List.copyOf(alternatives),
                complete && !emptyTag,
                emptyTag ? "Empty source tag: NeoForge display barrier is not an ingredient; matching remains unsupported"
                        : complete ? "One item from this OR set; original item/tag identities retained"
                        : "Alternative expansion exceeded a bound; omitted members remain unknown, not absent");
    }
    private static NormalizedRecipe.Requirement unsupported(int position, String detail) {
        return new NormalizedRecipe.Requirement(position, 1, "unsupported", List.of(), List.of(), List.of(), false, detail);
    }
    private static boolean bounded(ResourceLocation id) {
        return id != null && id.getNamespace().length() + 1L + id.getPath().length() <= NormalizedRecipe.MAX_ID_LENGTH;
    }
    /** Ranking reads only exact vanilla-class ingredient metadata, never opaque recipe output APIs. */
    public static RecipeSelection selectionRank(RecipeHolder<?> holder) {
        Recipe<?> recipe = holder.value();
        Class<?> recipeClass = recipe.getClass();
        boolean crafting = recipeClass == ShapedRecipe.class || recipeClass == ShapelessRecipe.class;
        boolean cooking = recipeClass == SmeltingRecipe.class || recipeClass == BlastingRecipe.class
                || recipeClass == SmokingRecipe.class || recipeClass == CampfireCookingRecipe.class;
        String id = holder.id().toString();
        if (!crafting && !cooking) return new RecipeSelection(2, Integer.MAX_VALUE, id);
        try {
            if (recipe.isSpecial()) return new RecipeSelection(1, Integer.MAX_VALUE, id);
            var ingredients = recipe.getIngredients();
            if (ingredients.size() > (crafting ? 9 : 1)) return new RecipeSelection(1, Integer.MAX_VALUE, id);
            int cost = 0;
            for (Ingredient ingredient : ingredients) {
                if (ingredient.isCustom() || !ingredient.isSimple()) return new RecipeSelection(1, Integer.MAX_VALUE, id);
                if (ingredient.isEmpty()) continue;
                var values = ingredient.getValues();
                if (values.length > NormalizedRecipe.MAX_SOURCE_VALUES) return new RecipeSelection(1, Integer.MAX_VALUE, id);
                int options = 0;
                for (var value : values) {
                    if (value instanceof Ingredient.ItemValue item) {
                        if (item.item().isEmpty()) return new RecipeSelection(1, Integer.MAX_VALUE, id);
                        options++;
                    } else if (value instanceof Ingredient.TagValue tag) {
                        int members = BuiltInRegistries.ITEM.getTag(tag.tag()).map(set -> set.size()).orElse(0);
                        if (members == 0 || members > NormalizedRecipe.MAX_ALTERNATIVES) return new RecipeSelection(1, Integer.MAX_VALUE, id);
                        options += members;
                    } else return new RecipeSelection(1, Integer.MAX_VALUE, id);
                    if (options > NormalizedRecipe.MAX_ALTERNATIVES) return new RecipeSelection(1, Integer.MAX_VALUE, id);
                }
                cost += options;
            }
            return new RecipeSelection(0, cost, id);
        } catch (RuntimeException | LinkageError exception) {
            // Normal extraction will retain an explicit failure; ranking must never abort the whole index.
            return new RecipeSelection(1, Integer.MAX_VALUE, id);
        }
    }
    private static final class Budget {
        final RetainedIngredientBudget retained = new RetainedIngredientBudget();
        int failures;
        int retentionLimited;
    }
}
