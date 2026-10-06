package dev.atmcompanion.knowledge;

import java.util.List;

/** Charges only retained facts; unsupported expansions cannot exhaust useful alternative capacity. */
public final class RetainedIngredientBudget {
    private final int maxAlternatives;
    private final int maxIdentities;
    private int alternatives;
    private int identities;
    public RetainedIngredientBudget() { this(RecipeIndex.MAX_TOTAL_ALTERNATIVES, RecipeIndex.MAX_TOTAL_IDENTITIES); }
    public RetainedIngredientBudget(int maxAlternatives, int maxIdentities) {
        if (maxAlternatives < 0 || maxAlternatives > RecipeIndex.MAX_TOTAL_ALTERNATIVES
                || maxIdentities < 0 || maxIdentities > RecipeIndex.MAX_TOTAL_IDENTITIES) throw new IllegalArgumentException("Invalid retained ingredient budget");
        this.maxAlternatives = maxAlternatives; this.maxIdentities = maxIdentities;
    }
    public NormalizedRecipe.Requirement retain(NormalizedRecipe.Requirement requirement, boolean recipeSupported) {
        int sources = requirement.sourceItems().size() + requirement.sourceTags().size();
        int options = requirement.alternatives().size();
        boolean keepOptions = recipeSupported && requirement.supported()
                && options <= maxAlternatives - alternatives && sources + options <= maxIdentities - identities;
        if (keepOptions) {
            alternatives += options;
            identities += sources + options;
            return requirement;
        }
        String reason = !recipeSupported ? "Recipe has unsupported semantics; expanded alternatives omitted"
                : !requirement.supported() ? "Incomplete/unsupported expansion omitted"
                : "Retained material identity budget exhausted; omitted alternatives remain unknown";
        if (sources > maxIdentities - identities) {
            return new NormalizedRecipe.Requirement(requirement.position(), requirement.count(), "unsupported",
                    List.of(), List.of(), List.of(), false, "Global source identity budget exhausted; material data unavailable");
        }
        identities += sources;
        return new NormalizedRecipe.Requirement(requirement.position(), requirement.count(), requirement.kind(),
                requirement.sourceItems(), requirement.sourceTags(), List.of(), false, requirement.detail() + "; " + reason);
    }
    public int alternativesUsed() { return alternatives; }
    public int identitiesUsed() { return identities; }
}
