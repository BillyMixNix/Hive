package dev.atmcompanion.knowledge;

import java.util.Arrays;
import java.util.List;

/** Pure normalized facts for tests, independent of Minecraft registry bootstrap. */
public final class RecipeFixtures {
    private RecipeFixtures() {}

    public static NormalizedRecipe.Requirement exact(int position, String item, int quantity) {
        return new NormalizedRecipe.Requirement(position, quantity, "exact", List.of(item), List.of(), List.of(item), true, "Runtime exact item");
    }

    public static NormalizedRecipe.Requirement choice(int position, int quantity, String... items) {
        return new NormalizedRecipe.Requirement(position, quantity, "tag", List.of(), List.of("fixture:materials"),
                Arrays.asList(items), true, "Runtime tag alternatives");
    }

    public static NormalizedRecipe recipe(String id, String output, int outputCount, NormalizedRecipe.Requirement... inputs) {
        return new NormalizedRecipe(id, "minecraft:crafting", "minecraft:crafting_shapeless",
                new NormalizedRecipe.Output(output, outputCount, true, false), Arrays.asList(inputs), "crafting", true, List.of());
    }

    public static NormalizedRecipe unsupported(String id, String output) {
        return new NormalizedRecipe(id, "fixture:machine", "fixture:machine",
                new NormalizedRecipe.Output(output, 1, true, false), List.of(), "machine", false,
                List.of("Fluids, energy and custom requirements have not been inspected"));
    }

    public static RecipeIndex index(NormalizedRecipe... recipes) {
        return index(List.of(recipes), false);
    }

    public static RecipeIndex index(List<NormalizedRecipe> recipes, boolean truncated) {
        int unknown = (int) recipes.stream().filter(recipe -> recipe.output() == null).count();
        int unsupported = (int) recipes.stream().filter(recipe -> !recipe.dependencySupported()).count();
        return new RecipeIndex(1, 7, "2026-09-22T12:34:56Z", recipes,
                new RecipeIndex.Stats(recipes.size() + (truncated ? 1 : 0), recipes.size(), recipes.size(), unknown,
                        unsupported, truncated, 1));
    }
}
