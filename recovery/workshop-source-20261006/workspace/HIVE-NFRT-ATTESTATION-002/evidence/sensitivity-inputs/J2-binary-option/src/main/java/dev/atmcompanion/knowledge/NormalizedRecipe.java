package dev.atmcompanion.knowledge;

import java.util.List;
import java.util.Objects;

/** Detached, versioned index facts; a preview is not proof of fixed output or executable crafting. */
public record NormalizedRecipe(String id, String type, String serializer, Output output,
                               List<Requirement> ingredients, String kind, boolean dependencySupported,
                               List<String> limitations, ExecutionRequirement execution) {
    public static final int MAX_REQUIREMENTS = 64;
    public static final int MAX_ALTERNATIVES = 256;
    public static final int MAX_SOURCE_VALUES = 64;
    public static final int MAX_ID_LENGTH = 256;
    /** Legacy fixtures have no execution evidence; material support never implies execution support. */
    public NormalizedRecipe(String id, String type, String serializer, Output output, List<Requirement> ingredients,
                            String kind, boolean dependencySupported, List<String> limitations) {
        this(id, type, serializer, output, ingredients, kind, dependencySupported, limitations, ExecutionRequirement.unknown());
    }
    public NormalizedRecipe {
        Objects.requireNonNull(id); Objects.requireNonNull(type); Objects.requireNonNull(serializer); Objects.requireNonNull(kind);
        Objects.requireNonNull(execution);
        if (id.length() > MAX_ID_LENGTH || type.length() > MAX_ID_LENGTH || serializer.length() > MAX_ID_LENGTH) throw new IllegalArgumentException("Recipe identity exceeds bound");
        ingredients = List.copyOf(ingredients);
        limitations = List.copyOf(limitations);
        if (ingredients.size() > MAX_REQUIREMENTS) throw new IllegalArgumentException("Too many recipe requirements");
        if (dependencySupported && (output == null || !output.fixed() || output.hasNonDefaultComponents()
                || ingredients.isEmpty() || ingredients.stream().anyMatch(requirement -> !requirement.supported()))) {
            throw new IllegalArgumentException("Supported dependency recipe must have fixed plain output and complete supported ingredients");
        }
    }
    /** Static recipe requirements only. Grid fit is not evidence that the player can access that grid. */
    public record ExecutionRequirement(String kind, boolean fits2x2, boolean fits3x3, int width, int height, int cookingTicks) {
        public ExecutionRequirement {
            Objects.requireNonNull(kind);
            if (!List.of("unknown", "crafting", "smelting", "blasting", "smoking", "campfire").contains(kind)
                    || width < 0 || width > 3 || height < 0 || height > 3 || cookingTicks < 0
                    || (width == 0) != (height == 0)) throw new IllegalArgumentException("Invalid execution requirement");
            if (kind.equals("crafting")) {
                if (cookingTicks != 0 || fits2x2 && !fits3x3) throw new IllegalArgumentException("Invalid crafting execution requirement");
                if (width > 0 && (fits2x2 != (width <= 2 && height <= 2) || !fits3x3))
                    throw new IllegalArgumentException("Grid fit contradicts known shaped dimensions");
            } else if (fits2x2 || fits3x3 || width != 0 || height != 0
                    || kind.equals("unknown") && cookingTicks != 0) throw new IllegalArgumentException("Noncrafting execution cannot claim grid fit");
        }
        public static ExecutionRequirement unknown() { return new ExecutionRequirement("unknown", false, false, 0, 0, 0); }
    }
    public record Output(String item, int count, boolean fixed, boolean hasNonDefaultComponents) {
        public Output {
            Objects.requireNonNull(item);
            if (item.length() > MAX_ID_LENGTH) throw new IllegalArgumentException("Output identity exceeds bound");
            if (count < 1) throw new IllegalArgumentException("Output count must be positive");
        }
    }
    /** alternatives is the current tag-expanded OR set, never a list of jointly required items. */
    public record Requirement(int position, int count, String kind, List<String> sourceItems,
                              List<String> sourceTags, List<String> alternatives, boolean alternativesComplete,
                              String detail) {
        public Requirement {
            if (position < 0 || count < 1) throw new IllegalArgumentException("Invalid ingredient position/count");
            Objects.requireNonNull(kind); Objects.requireNonNull(detail);
            sourceItems = sorted(sourceItems); sourceTags = sorted(sourceTags); alternatives = sorted(alternatives);
            if (sourceItems.size() > MAX_SOURCE_VALUES || sourceTags.size() > MAX_SOURCE_VALUES
                    || alternatives.size() > MAX_ALTERNATIVES) throw new IllegalArgumentException("Ingredient bounds exceeded");
        }
        public boolean supported() {
            return alternativesComplete && !alternatives.isEmpty()
                    && (kind.equals("exact") || kind.equals("tag") || kind.equals("alternatives"));
        }
        private static List<String> sorted(List<String> values) {
            return values.stream().map(value -> {
                Objects.requireNonNull(value);
                if (value.length() > MAX_ID_LENGTH) throw new IllegalArgumentException("Ingredient identity exceeds bound");
                return value;
            }).distinct().sorted().toList();
        }
    }
}
