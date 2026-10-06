package dev.atmcompanion.planning;

import dev.atmcompanion.state.SnapshotFormatter;
import java.util.ArrayList;
import java.util.List;

public final class PlanFormatter {
    public static final int MAX_LINES = 8;
    private PlanFormatter() {}
    public static String formatStatusLine(PlanResult plan) {
        return "STATUS: " + plan.status() + " | Goal: " + plan.quantity() + " x " + plan.goal();
    }
    public static List<String> format(PlanResult plan) {
        List<String> lines = new ArrayList<>();
        lines.add("GOAL " + plan.quantity() + " x " + plan.goal() + " | materials: " + plan.status());
        lines.add("Reserved inventory: " + resources(plan.ownedRequirements(), "other item types"));
        lines.add("Missing leaves: " + resources(plan.missingRequirements(), "other missing types"));
        lines.add("Next operation: " + plan.execution().status() + (plan.execution().station() == null ? "" : " | " + plan.execution().station()));
        var next = plan.nextAction();
        lines.add("Next: " + next.kind() + " " + next.quantity() + " x " + next.item());
        lines.add("Why: " + next.reason());
        lines.add("Depth " + plan.metrics().depth() + " | nodes " + plan.metrics().expandedNodes() + " | alternatives " + plan.alternativePaths().size()
                + " | unsupported " + plan.unsupportedSteps().size() + (plan.metrics().searchTruncated() ? " | search limited" : "")
                + (!plan.metrics().indexComplete() ? " | index partial" : ""));
        lines.add("Further execution unverified: modded permissions, safe access, machines/storage and future fuel. Operator detail: debug plan.");
        return lines.stream().limit(MAX_LINES).map(SnapshotFormatter::boundLine).toList();
    }
    private static String resources(List<PlanResult.Resource> resources, String suffix) {
        if (resources.isEmpty()) return "none";
        return resources.stream().limit(3).map(r -> r.quantity() + "x " + r.item()).collect(java.util.stream.Collectors.joining(", "))
                + (resources.size() > 3 ? "; +" + (resources.size() - 3) + " " + suffix : "");
    }
}
