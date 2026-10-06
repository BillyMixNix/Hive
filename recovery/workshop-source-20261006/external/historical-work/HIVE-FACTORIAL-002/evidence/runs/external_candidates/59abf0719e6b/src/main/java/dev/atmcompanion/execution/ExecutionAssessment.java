package dev.atmcompanion.execution;

import dev.atmcompanion.planning.PlanResult;
import java.util.List;

/** Only one operation is assessed. Met observations are not a guarantee of modded interaction permission. */
public record ExecutionAssessment(String status, String recipeId, long operations, String station,
                                  List<PlanResult.Resource> inputs, List<FuelReservation> fuel,
                                  List<String> blockers, List<String> unverifiedConditions,
                                  PlanResult.Action nextAction, ExecutionContext observation) {
    public ExecutionAssessment {
        inputs = List.copyOf(inputs); fuel = List.copyOf(fuel);
        blockers = List.copyOf(blockers); unverifiedConditions = List.copyOf(unverifiedConditions);
        if (operations < 0 || operations > 1) throw new IllegalArgumentException("M3 assesses at most one operation");
    }
    public record FuelReservation(String source, int slot, String item, int count, long burnTicks) {}
    public static ExecutionAssessment unavailable(String reason) {
        return new ExecutionAssessment("unknown", "", 0, "", List.of(), List.of(), List.of(), List.of(reason), null, null);
    }
    public static ExecutionAssessment unnecessary() {
        return new ExecutionAssessment("not_needed", "", 0, "", List.of(), List.of(), List.of(), List.of(), null, null);
    }
}
