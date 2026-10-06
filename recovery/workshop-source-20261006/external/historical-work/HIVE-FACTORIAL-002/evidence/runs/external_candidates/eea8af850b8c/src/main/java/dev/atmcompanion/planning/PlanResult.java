package dev.atmcompanion.planning;

import java.util.List;
import dev.atmcompanion.execution.ExecutionAssessment;

/** Plain, versioned planning output. Planned resources never become claims about current ownership. */
public record PlanResult(int schemaVersion, String goal, long quantity, String status,
                         List<Resource> ownedRequirements, List<Resource> missingRequirements,
                         List<Step> selectedPath, Action nextAction, List<Alternative> alternativePaths,
                         List<Issue> unsupportedSteps, Metrics metrics, List<String> limitations,
                         ExecutionAssessment execution) {
    public PlanResult(int schemaVersion, String goal, long quantity, String status,
                      List<Resource> ownedRequirements, List<Resource> missingRequirements, List<Step> selectedPath,
                      Action nextAction, List<Alternative> alternativePaths, List<Issue> unsupportedSteps,
                      Metrics metrics, List<String> limitations) {
        this(schemaVersion, goal, quantity, status, ownedRequirements, missingRequirements, selectedPath, nextAction,
                alternativePaths, unsupportedSteps, metrics, limitations, ExecutionAssessment.unavailable("Execution has not been observed"));
    }
    public PlanResult {
        ownedRequirements = List.copyOf(ownedRequirements);
        missingRequirements = List.copyOf(missingRequirements);
        selectedPath = List.copyOf(selectedPath);
        alternativePaths = List.copyOf(alternativePaths);
        unsupportedSteps = List.copyOf(unsupportedSteps);
        limitations = List.copyOf(limitations);
    }
    public record Resource(String item, long quantity) {}
    public record Step(String recipeId, String output, long outputQuantity, long crafts,
                       String type, int depth, List<String> limitations, List<AllocatedIngredient> ingredients) {
        public Step(String recipeId, String output, long outputQuantity, long crafts, String type, int depth, List<String> limitations) {
            this(recipeId, output, outputQuantity, crafts, type, depth, limitations, List.of());
        }
        public Step { limitations = List.copyOf(limitations); ingredients = List.copyOf(ingredients); }
    }
    /** Exact selected member counts for each ingredient position across this step's operations. */
    public record AllocatedIngredient(int position, String item, long quantity) {}
    public record Issue(String item, long quantity, String kind, String reason) {}
    public record Action(String kind, String item, long quantity, String recipeId, String reason) {}
    public record Alternative(String firstRecipe, long missingItems, int unsupportedSteps, int steps,
                              List<Resource> missingRequirements, List<Issue> blockers, Action nextAction, String executionStatus) {
        public Alternative(String firstRecipe, long missingItems, int unsupportedSteps, int steps) {
            this(firstRecipe, missingItems, unsupportedSteps, steps, List.of(), List.of(), null, "unknown");
        }
        public Alternative { missingRequirements = List.copyOf(missingRequirements); blockers = List.copyOf(blockers); }
    }
    public record Metrics(long indexGeneration, int expandedNodes, int depth,
                          boolean searchTruncated, boolean indexComplete, long planningNanos) {}
    public PlanResult withExecution(ExecutionAssessment assessment) {
        Action action = unsupportedSteps.isEmpty() && !status.equals("already_owned") && assessment.nextAction() != null
                ? assessment.nextAction() : nextAction;
        return new PlanResult(2, goal, quantity, status, ownedRequirements, missingRequirements, selectedPath, action,
                alternativePaths, unsupportedSteps, metrics, limitations, assessment);
    }
    public PlanResult withAlternatives(List<Alternative> alternatives) {
        return new PlanResult(2, goal, quantity, status, ownedRequirements, missingRequirements, selectedPath, nextAction,
                alternatives, unsupportedSteps, metrics, limitations, execution);
    }
}
