package dev.atmcompanion.execution;

import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.planning.PlanResult;
import dev.atmcompanion.state.Observation;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Pure one-operation feasibility assessment. Never schedules actions or transfers items. */
public final class ExecutionAssessor {
    private ExecutionAssessor() {}
    public static ExecutionAssessment assess(PlanResult plan, NormalizedRecipe recipe,
                                              OperationInputs.Result inputs, ExecutionContext context) {
        if (plan.status().equals("already_owned")) return ExecutionAssessment.unnecessary();
        if (!plan.unsupportedSteps().isEmpty() || !recipe.dependencySupported())
            return ExecutionAssessment.unavailable("The selected material path contains unsupported or limited steps");
        if (!inputs.ready()) return result(plan, recipe, inputs, context, inputs.status().equals("missing") ? "blocked" : "unknown", null,
                List.of(), List.of(inputs.detail()), null);
        var op = context.operation().data();
        if (op == null || !op.recipeId().equals(recipe.id())) return result(plan, recipe, inputs, context, "unknown", null,
                List.of(), List.of("Current operation observation unavailable: " + context.operation().detail()), null);
        if (!op.kind().equals("crafting") && !op.kind().equals("cooking")) return result(plan, recipe, inputs, context, "unknown", null,
                List.of(), List.of("Operation kind is not supported"), null);
        if (op.unlockAllowed().data() == null) return result(plan, recipe, inputs, context, "unknown", null,
                List.of(), List.of("Recipe unlock status was not observed"), null);
        if (!op.unlockAllowed().data()) return result(plan, recipe, inputs, context, "blocked", null,
                List.of(), List.of("Limited crafting is enabled and this recipe is not unlocked"), action(recipe, "unlock_recipe", "Unlock this recipe before crafting it."));
        if (op.kind().equals("crafting") && op.fits2x2())
            return result(plan, recipe, inputs, context, "observed_conditions_met", "player_2x2", List.of(), List.of(),
                    action(recipe, "prepare_recipe", "Check the output preview: one operation's inputs and the player 2x2 grid fit were observed. Overlapping crafting recipe selection is unverified."));
        if (op.kind().equals("crafting") && !op.fits3x3()) return result(plan, recipe, inputs, context, "unknown", null,
                List.of(), List.of("Recipe does not fit a supported vanilla crafting grid"), null);
        if (op.kind().equals("cooking")) {
            if (!Boolean.TRUE.equals(op.playerInputMatches().data()) || !Boolean.TRUE.equals(op.uniqueCookingMatch().data())
                    || op.cookingTicks().data() == null)
                return result(plan, recipe, inputs, context, "unknown", null, List.of(), List.of(
                        "Cooking needs a matching live input, a positive duration and a unique runtime recipe match; one or more were not established"), null);
            if (inputs.inputs().size() != 1 || inputs.inputs().getFirst().quantity() != 1
                    || !inputs.inputs().getFirst().item().equals(op.selectedInputItem()))
                return result(plan, recipe, inputs, context, "unknown", null, List.of(), List.of("Live cooking input differs from the chosen material allocation"), null);
        }
        var stations = context.stations().stream().filter(s -> s.kind().equals(op.stationKind())).toList();
        if (stations.isEmpty()) {
            String detail = "No compatible " + op.stationKind() + " observed in the loaded radius-8 cube";
            return result(plan, recipe, inputs, context, context.scan().complete() ? "blocked" : "unknown", null, List.of(),
                    List.of(detail + (context.scan().complete() ? "" : "; scan coverage is incomplete")),
                    action(recipe, "locate_station", detail + ". Move near a compatible station and query again."));
        }
        return stations.stream().map(s -> station(plan, recipe, inputs, context, s))
                .min(Comparator.comparingInt((ExecutionAssessment a) -> rank(a.status()))).orElseThrow();
    }
    private static ExecutionAssessment station(PlanResult plan, NormalizedRecipe recipe, OperationInputs.Result inputs,
                                                ExecutionContext ctx, ExecutionContext.Station station) {
        String location = station.blockId() + " at " + station.x() + "/" + station.y() + "/" + station.z();
        if (!station.vanillaMayInteract()) return result(plan, recipe, inputs, ctx, "blocked", location, List.of(),
                List.of("Vanilla world-border or spawn-protection check prevents interaction"), action(recipe, "inspect_station", "Find a station where vanilla interaction is permitted."));
        if (!station.withinReach()) return result(plan, recipe, inputs, ctx, "blocked", location, List.of(),
                List.of("Station is outside the observed block interaction range"), action(recipe, "approach_station", "Move within reach of " + location + " and query again; no safe path was calculated."));
        if (station.lockAllows().data() == null) return result(plan, recipe, inputs, ctx, "unknown", location, List.of(),
                List.of("Station lock/access inspection unavailable"), null);
        if (!station.lockAllows().data()) return result(plan, recipe, inputs, ctx, "blocked", location, List.of(),
                List.of("Vanilla station lock does not match the held item"), action(recipe, "inspect_station", "Resolve the vanilla lock on " + location + "."));
        if (station.kind().equals("crafting")) return result(plan, recipe, inputs, ctx, "observed_conditions_met", location,
                List.of(), List.of(), action(recipe, "prepare_recipe", "Check the output preview: one operation's inputs and a reachable 3x3 table were observed at " + location + ". Overlapping crafting selection is unverified."));
        var details = station.details().data();
        if (details == null) return result(plan, recipe, inputs, ctx, "unknown", location, List.of(),
                List.of("Station detail inspection unavailable: " + station.details().detail()), null);
        if (station.kind().equals("campfire")) {
            if (!details.lit() || details.waterlogged() || details.freeCampfireSlots() == 0)
                return result(plan, recipe, inputs, ctx, "blocked", location, List.of(), List.of("Campfire needs to be lit, dry and have a free cooking slot"),
                        action(recipe, "inspect_station", "Prepare a lit, dry campfire with a free slot at " + location + "."));
            return result(plan, recipe, inputs, ctx, "observed_conditions_met", location, List.of(), List.of(),
                    action(recipe, "prepare_recipe", "One matching input and a lit campfire's free slot were observed. Cook one operation at " + location + "; its output drops into the world."));
        }
        if (details.stacks().size() != 3 || details.timers().data() == null)
            return result(plan, recipe, inputs, ctx, "unknown", location, List.of(), List.of("Furnace slots or typed timing data unavailable"), null);
        if (details.stacks().getFirst().count() != 0)
            return result(plan, recipe, inputs, ctx, "blocked", location, List.of(), List.of("Station input is occupied; existing work is not part of player-owned materials"),
                    action(recipe, "inspect_station", "Finish or inspect the existing input at " + location + " before loading this new operation."));
        if (!Boolean.TRUE.equals(details.inputCompatible().data()) || !Boolean.TRUE.equals(details.outputCompatible().data()))
            return result(plan, recipe, inputs, ctx,
                    details.inputCompatible().data() == null || details.outputCompatible().data() == null ? "unknown" : "blocked", location,
                    List.of(), List.of("Selected input or result cannot be confirmed to fit the station slots"),
                    action(recipe, "inspect_station", "Check the input/output slots at " + location + " before starting this operation."));
        int duration = ctx.operation().data().cookingTicks().data();
        long heat = Math.max(0, details.timers().data().remainingBurnTicks() - 1L);
        List<ExecutionAssessment.FuelReservation> fuel = new ArrayList<>();
        if (heat > 0) fuel.add(new ExecutionAssessment.FuelReservation("station_heat", -1, null, 0, heat));
        if (heat >= duration) return ready(plan, recipe, inputs, ctx, location, fuel);
        var currentFuel = details.stacks().get(1);
        Integer burn = details.fuelTicksPerItem().data();
        if (currentFuel.count() > 0) {
            if (burn != null && burn > 0 && heat + burn >= duration) {
                fuel.add(new ExecutionAssessment.FuelReservation("station", 1, currentFuel.item(), 1, burn));
                return ready(plan, recipe, inputs, ctx, location, fuel);
            }
            return result(plan, recipe, inputs, ctx, "unknown", location, fuel,
                    List.of("Existing fuel does not establish completion from current heat plus one ignition; queued fuel/remainders are not scheduled"),
                    action(recipe, "inspect_station", "Inspect existing fuel at " + location + "; this check models one new fuel item, not a fuel queue."));
        }
        for (var option : ctx.fuelSlots()) {
            Integer ticks = option.burnTicksPerItem().data();
            if (option.availableAfterReservation() > 0 && ticks != null && ticks > 0
                    && details.compatibleFuelSlots().contains(option.slot()) && heat + ticks >= duration) {
                fuel.add(new ExecutionAssessment.FuelReservation("player", option.slot(), option.item(), 1, ticks));
                return ready(plan, recipe, inputs, ctx, location, fuel);
            }
        }
        boolean unknown = ctx.fuelSlots().stream().anyMatch(f -> f.availableAfterReservation() > 0 && f.burnTicksPerItem().data() == null);
        return result(plan, recipe, inputs, ctx, unknown ? "unknown" : "blocked", location, fuel,
                List.of("No unreserved compatible player fuel item was observed that covers the remaining " + (duration - heat) + " ticks in one ignition"),
                action(recipe, "supply_fuel", "Supply one compatible fuel item lasting at least " + (duration - heat) + " ticks at " + location + ". Shorter fuel sequences are not scheduled."));
    }
    private static ExecutionAssessment ready(PlanResult p, NormalizedRecipe r, OperationInputs.Result i, ExecutionContext c,
                                              String s, List<ExecutionAssessment.FuelReservation> fuel) {
        return result(p, r, i, c, "observed_conditions_met", s, fuel, List.of(),
                action(r, "prepare_recipe", "One operation's input, output space and heat/fuel were observed at " + s + ". Full-path materials remain reserved; future operations need fresh checks."));
    }
    private static ExecutionAssessment result(PlanResult p, NormalizedRecipe r, OperationInputs.Result i, ExecutionContext c,
                                               String status, String station, List<ExecutionAssessment.FuelReservation> fuel,
                                               List<String> blockers, PlanResult.Action action) {
        if (action == null && i.ready() && !status.equals("observed_conditions_met"))
            action = action(r, "inspect_step", "Next operation is " + status + ": "
                    + (blockers.isEmpty() ? "required execution evidence is unavailable" : blockers.getFirst()));
        return new ExecutionAssessment(status, r.id(), 1, station, i.inputs(), fuel, blockers,
                List.of("Snapshot feasibility only; modded claims, interaction hooks, line of sight and safe access are unverified.",
                        "Crafting output preview must be checked: overlapping crafting recipe selection is unverified.",
                        "Only one next operation; no whole-chain fuel scheduling, station output ownership or automatic action."), action, c);
    }
    private static PlanResult.Action action(NormalizedRecipe recipe, String kind, String reason) {
        return new PlanResult.Action(kind, recipe.output().item(), recipe.output().count(), recipe.id(), reason);
    }
    public static int rank(String status) {
        return switch (status) { case "not_needed", "observed_conditions_met" -> 0; case "blocked" -> 1; default -> 2; };
    }
}
