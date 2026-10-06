package dev.atmcompanion.planning;

import dev.atmcompanion.state.Observation;
import java.util.List;

/** AI-ready data boundary only: no transmission, secrets, account IDs or automatic AI projection. */
public record PlanningReport(int schemaVersion, String timestamp, PlanResult plan,
                             Observation<QuestContext> questContext, KnowledgeGraph knowledgeGraph, Timings timings) {
    public PlanningReport(int schemaVersion, String timestamp, PlanResult plan, Observation<QuestContext> questContext, KnowledgeGraph knowledgeGraph) {
        this(schemaVersion, timestamp, plan, questContext, knowledgeGraph, new Timings(0, 0, 0, 0));
    }
    public record Timings(long materialNanos, long executionNanos, long questNanos, long totalNanos) {}
    public record QuestContext(String scope, int total, int completed, int available, int blocked,
                               List<QuestOption> options, String ordering) {
        public QuestContext { options = List.copyOf(options); }
    }
    public record QuestOption(String id, String title) {}
}
