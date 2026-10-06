package dev.atmcompanion.knowledge;

import com.mojang.logging.LogUtils;
import dev.atmcompanion.state.Observation;
import dev.atmcompanion.state.SnapshotService;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.ShapedRecipe;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import org.slf4j.Logger;

/** M1-compatible per-player view over the lifecycle-built M2 index. */
public final class RecipeService {
    public static final int MAX_RECIPES_SCANNED = 50_000;
    public static final int MAX_MATCHES = 8;
    public static final int MAX_ALTERNATIVES = 32;
    public static final long MAX_SCAN_NANOS = 100_000_000L;
    private static final Logger LOGGER = LogUtils.getLogger();

    public RecipeReport find(ServerPlayer player, ResourceLocation output) {
        SnapshotService.requireServerThread(player);
        if (!BuiltInRegistries.ITEM.containsKey(output)) throw new IllegalArgumentException("Unknown registered item: " + output);
        RecipeIndex index = RuntimeKnowledge.get(player.getServer());
        var routes = index.recipesFor(output.toString());
        List<RecipeReport.Candidate> matches = new ArrayList<>();
        int unreadable = 0;
        boolean scanTruncated = !index.complete();
        boolean matchesTruncated = routes.size() > MAX_MATCHES || index.recipesForTruncated(output.toString());
        for (NormalizedRecipe indexed : routes.stream().limit(MAX_MATCHES).toList()) {
            try {
                RecipeHolder<?> holder = player.getServer().getRecipeManager().byKey(ResourceLocation.parse(indexed.id()))
                        .orElseThrow(() -> new IllegalStateException("Indexed recipe is no longer present: " + indexed.id()));
                ItemStack result = holder.value().getResultItem(player.registryAccess());
                if (result.isEmpty() || !BuiltInRegistries.ITEM.getKey(result.getItem()).equals(output)) {
                    unreadable++;
                    continue;
                }
                matches.add(describe(player, holder, result));
            } catch (RuntimeException | LinkageError exception) {
                unreadable++;
                if (unreadable == 1) LOGGER.warn("ATM Companion could not inspect indexed recipe {}; further failures in this query are counted", indexed.id(), exception);
            }
        }
        if (unreadable > 1) LOGGER.warn("ATM Companion could not inspect {} recipes in the latest query", unreadable);
        return new RecipeReport(output.toString(), index.stats().inspectedRecipes(), scanTruncated, matches, matchesTruncated, unreadable);
    }
    public RecipeReport.Candidate describe(ServerPlayer player, RecipeHolder<?> holder, ItemStack result) {
        SnapshotService.requireServerThread(player);
        Recipe<?> recipe = holder.value();
        String type = BuiltInRegistries.RECIPE_TYPE.getKey(recipe.getType()).toString();
        // Subclasses can override matching semantics; exact classes deliberately keep this spike honest.
        boolean standardCrafting = recipe.getClass() == ShapedRecipe.class || recipe.getClass() == ShapelessRecipe.class;
        if (!standardCrafting || recipe.isSpecial()) return unsupported(holder, result, type, "Unsupported recipe type/class; machine, fluid, dynamic and custom conditions were not inspected");
        var inputs = recipe.getIngredients();
        if (inputs.size() > 9) return unsupported(holder, result, type, "Crafting grid exceeds supported 3x3 bounds");
        List<RecipeReport.Ingredient> requirements = new ArrayList<>();
        List<List<Integer>> matchingSlots = new ArrayList<>();
        boolean hasEmptyTag = false;
        Map<Integer, Integer> counts = new HashMap<>();
        for (int slot = 0; slot < 36; slot++) counts.put(slot, player.getInventory().getItem(slot).getCount());
        for (int position = 0; position < inputs.size(); position++) {
            Ingredient ingredient = inputs.get(position);
            if (ingredient.isCustom()) return unsupported(holder, result, type, "Custom ingredient semantics are unsupported, including simple custom ingredients");
            if (ingredient.isEmpty()) continue;
            if (!ingredient.isSimple()) return unsupported(holder, result, type, "Custom/component-sensitive ingredient semantics are unsupported; no fixed ingredient claim made");
            Ingredient.Value[] values = ingredient.getValues();
            if (values.length > 64) return unsupported(holder, result, type, "Ingredient source alternatives exceed supported bounds");
            LinkedHashSet<String> alternatives = new LinkedHashSet<>();
            LinkedHashSet<String> tags = new LinkedHashSet<>();
            boolean alternativesTruncated = false;
            boolean emptyTag = false;
            for (Ingredient.Value value : values) {
                if (value instanceof Ingredient.ItemValue itemValue) {
                    if (alternatives.size() < MAX_ALTERNATIVES) alternatives.add(BuiltInRegistries.ITEM.getKey(itemValue.item().getItem()).toString());
                    else alternativesTruncated = true;
                } else if (value instanceof Ingredient.TagValue tagValue) {
                    tags.add(tagValue.tag().location().toString());
                    var holders = BuiltInRegistries.ITEM.getTag(tagValue.tag());
                    if (holders.isEmpty() || holders.get().size() == 0) emptyTag = true;
                    else {
                        var iterator = holders.get().iterator();
                        int inspected = 0;
                        while (iterator.hasNext() && inspected++ <= MAX_ALTERNATIVES) {
                            var item = iterator.next();
                            if (alternatives.size() < MAX_ALTERNATIVES) alternatives.add(BuiltInRegistries.ITEM.getKey(item.value()).toString());
                            else { alternativesTruncated = true; break; }
                        }
                        if (iterator.hasNext()) alternativesTruncated = true;
                    }
                } else return unsupported(holder, result, type, "Unknown vanilla ingredient value");
            }
            hasEmptyTag |= emptyTag;
            int matchingCount = 0;
            List<Integer> slots = new ArrayList<>();
            for (int slot = 0; slot < 36; slot++) {
                ItemStack owned = player.getInventory().getItem(slot);
                if (!owned.isEmpty() && matchesOriginalValues(owned, values)) {
                    slots.add(slot);
                    matchingCount = (int) Math.min(Integer.MAX_VALUE, (long) matchingCount + owned.getCount());
                }
            }
            matchingSlots.add(slots);
            requirements.add(new RecipeReport.Ingredient(position, "runtime_resolved_alternatives", List.copyOf(alternatives), List.copyOf(tags),
                    alternativesTruncated, matchingCount,
                    "One item satisfying original item/tag values; alternatives reflect loaded tags, never empty-tag display placeholders. Per-position counts overlap and must not be added." + (emptyTag ? " Contains an empty tag: runtime placeholder matching is unsupported." : "")));
        }
        if (requirements.isEmpty()) return unsupported(holder, result, type, "No ordinary crafting ingredients exposed");
        if (hasEmptyTag) return new RecipeReport.Candidate(holder.id().toString(), type, result.getCount(), "unsupported_empty_tag", requirements,
                Observation.unavailable("Contains an empty tag; NeoForge's barrier display placeholder is not treated as a real ingredient. Overall runtime matching is unsupported."));
        return new RecipeReport.Candidate(holder.id().toString(), type, result.getCount(), "vanilla_crafting_ingredients",
                requirements, new Observation<>(dev.atmcompanion.state.CapabilityStatus.AVAILABLE,
                IngredientAllocation.canSatisfy(matchingSlots, counts),
                "Ingredient availability only, one craft, main inventory slots 0..35; overlapping alternatives allocated once. Does not establish crafting-table access, recipe unlock, output components or overall craftability."));
    }
    private static boolean matchesOriginalValues(ItemStack owned, Ingredient.Value[] values) {
        for (Ingredient.Value value : values) {
            if (value instanceof Ingredient.ItemValue item && owned.is(item.item().getItem())) return true;
            if (value instanceof Ingredient.TagValue tag && owned.is(tag.tag())) return true;
        }
        return false;
    }
    private RecipeReport.Candidate unsupported(RecipeHolder<?> holder, ItemStack result, String type, String reason) {
        return new RecipeReport.Candidate(holder.id().toString(), type, result.getCount(), "unsupported", List.of(), Observation.unavailable(reason));
    }
}
