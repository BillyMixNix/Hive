package dev.atmcompanion.knowledge;

import dev.atmcompanion.state.Observation;
import java.util.List;

/** Recipe spike: alternatives remain alternatives; unsupported semantics are explicitly unknown. */
public record RecipeReport(String outputItem, int scannedRecipes, boolean scanTruncated,
                           List<Candidate> recipes, boolean matchesTruncated, int unreadableRecipes) {
    public RecipeReport { recipes = List.copyOf(recipes); }
    public record Candidate(String recipeId, String recipeType, int outputCount, String support,
                            List<Ingredient> ingredients, Observation<Boolean> inventorySatisfiesIngredients) {
        public Candidate { ingredients = List.copyOf(ingredients); }
    }
    public record Ingredient(int position, String representation, List<String> alternatives, List<String> sourceTags,
                             boolean alternativesTruncated, int matchingItemsInMainInventory, String detail) {
        public Ingredient { alternatives = List.copyOf(alternatives); sourceTags = List.copyOf(sourceTags); }
    }
}
