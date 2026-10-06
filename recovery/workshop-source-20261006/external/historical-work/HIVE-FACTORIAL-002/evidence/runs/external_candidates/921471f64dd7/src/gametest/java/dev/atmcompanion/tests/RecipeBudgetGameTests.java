package dev.atmcompanion.tests;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.knowledge.RecipeIndex;
import dev.atmcompanion.knowledge.RecipeIndexBuilder;
import dev.atmcompanion.planning.BoundedJson;
import dev.atmcompanion.planning.DeterministicPlanner;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import net.minecraft.core.NonNullList;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.crafting.CraftingBookCategory;
import net.minecraft.world.item.crafting.Ingredient;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;

@GameTestHolder("atm_companion_tests")
@PrefixGameTestTemplate(false)
public final class RecipeBudgetGameTests {
    @GameTest(template = "empty", timeoutTicks = 300)
    public static void wideEarlierRecipesCannotStarveActualVanillaPickaxe(GameTestHelper helper) throws Exception {
        var server = helper.getLevel().getServer();
        var vanilla = server.getRecipeManager().byKey(ResourceLocation.parse("minecraft:diamond_pickaxe")).orElseThrow();
        Item[] choices = BuiltInRegistries.ITEM.stream().filter(item -> item != Items.AIR).limit(64).toArray(Item[]::new);
        helper.assertTrue(choices.length == 64, "Fixture requires 64 real registered item alternatives");
        var wideIngredient = Ingredient.of(choices);
        var definitions = new ArrayList<RecipeHolder<?>>();
        for (int i = 0; i < 4_000; i++) {
            var recipe = new ShapelessRecipe("", CraftingBookCategory.MISC, new ItemStack(Items.STONE),
                    NonNullList.of(Ingredient.EMPTY, wideIngredient));
            definitions.add(new RecipeHolder<>(ResourceLocation.fromNamespaceAndPath("aaa_budget", "wide_" + i), recipe));
        }
        definitions.add(vanilla);
        helper.assertTrue(4_000L * choices.length > RecipeIndex.MAX_TOTAL_ALTERNATIVES,
                "Fixture must exceed the actual global retained-alternative cap");
        var index = RecipeIndexBuilder.build(server, 70_001, definitions);
        verify(helper, index, definitions.size());

        Collections.reverse(definitions);
        var reversed = RecipeIndexBuilder.build(server, 70_002, definitions);
        verify(helper, reversed, definitions.size());
        helper.assertTrue(index.recipesById().equals(reversed.recipesById()),
                "Material facts/budget admission changed with source iteration order");
        Files.createDirectories(Path.of("evidence"));
        Files.writeString(Path.of("evidence/m2-budget-regression.json"), BoundedJson.encode(Map.of(
                "fixtureDefinitions", definitions.size(), "potentialWideAlternatives", 4_000L * choices.length,
                "globalAlternativeCap", RecipeIndex.MAX_TOTAL_ALTERNATIVES, "stats", index.stats(),
                "retainedAlternatives", alternatives(index), "reversedInputFactsMatch", true,
                "pickaxe", index.recipesById().get("minecraft:diamond_pickaxe"))));
        helper.succeed();
    }

    private static void verify(GameTestHelper helper, RecipeIndex index, int totalDefinitions) {
        helper.assertTrue(index.stats().indexedRecipes() == totalDefinitions,
                "Fixture indexing unexpectedly hit another bound before testing ingredient admission");
        var pickaxe = index.recipesById().get("minecraft:diamond_pickaxe");
        helper.assertTrue(pickaxe != null && pickaxe.dependencySupported(),
                "Earlier wide recipes starved the actual vanilla pickaxe");
        helper.assertTrue(pickaxe.ingredients().size() == 5 && pickaxe.ingredients().stream().allMatch(NormalizedRecipe.Requirement::supported),
                "Pickaxe lost its five complete ingredient positions");
        var plan = new DeterministicPlanner().plan(index, "minecraft:diamond_pickaxe", 1,
                Map.of("minecraft:diamond", 3L, "minecraft:stick", 2L));
        helper.assertTrue(plan.status().equals("materials_ready") && plan.missingRequirements().isEmpty(),
                "Real pickaxe no longer recognizes exactly 3 diamonds and 2 sticks");
        helper.assertTrue(alternatives(index) <= RecipeIndex.MAX_TOTAL_ALTERNATIVES,
                "Fix escaped the original global alternative bound");
        long identities = index.recipesById().values().stream().flatMap(recipe -> recipe.ingredients().stream())
                .mapToLong(r -> (long) r.alternatives().size() + r.sourceItems().size() + r.sourceTags().size()).sum();
        helper.assertTrue(identities <= RecipeIndex.MAX_TOTAL_IDENTITIES, "Fix escaped the original identity bound");
        helper.assertTrue(index.stats().unsupportedRecipes() > 0, "Exhausted capacity must still be explicitly unknown");
        helper.assertTrue(index.recipesById().values().stream().filter(recipe -> !recipe.dependencySupported())
                .flatMap(recipe -> recipe.ingredients().stream()).noneMatch(NormalizedRecipe.Requirement::supported),
                "Budget-limited one-input recipes retained an incorrectly known ingredient");
    }

    private static long alternatives(RecipeIndex index) {
        return index.recipesById().values().stream().flatMap(recipe -> recipe.ingredients().stream())
                .mapToLong(requirement -> requirement.alternatives().size()).sum();
    }
}
