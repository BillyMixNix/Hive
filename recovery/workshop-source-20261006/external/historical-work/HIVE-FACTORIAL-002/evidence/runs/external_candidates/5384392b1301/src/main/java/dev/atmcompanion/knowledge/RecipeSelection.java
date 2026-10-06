package dev.atmcompanion.knowledge;

import java.util.Objects;

/** Cheap verified material models precede wide/opaque previews without preferring any namespace. */
public record RecipeSelection(int tier, int expandedCost, String recipeId) implements Comparable<RecipeSelection> {
    public RecipeSelection {
        if (tier < 0 || tier > 2 || expandedCost < 0) throw new IllegalArgumentException("Invalid recipe selection rank");
        Objects.requireNonNull(recipeId);
    }
    @Override public int compareTo(RecipeSelection other) {
        int result = Integer.compare(tier, other.tier);
        if (result == 0) result = Integer.compare(expandedCost, other.expandedCost);
        return result == 0 ? recipeId.compareTo(other.recipeId) : result;
    }
}
