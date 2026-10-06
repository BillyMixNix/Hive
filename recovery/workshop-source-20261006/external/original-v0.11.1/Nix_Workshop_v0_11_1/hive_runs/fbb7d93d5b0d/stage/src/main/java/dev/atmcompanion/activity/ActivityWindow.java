package dev.atmcompanion.activity;

import java.util.List;
import java.util.Objects;

/** Immutable snapshot of selected activity events and their summary. */
public record ActivityWindow(List<ActivityEvent> events, ActivitySummary summary) {
    public ActivityWindow {
        events = List.copyOf(events);
        Objects.requireNonNull(summary, "summary");
    }
}
