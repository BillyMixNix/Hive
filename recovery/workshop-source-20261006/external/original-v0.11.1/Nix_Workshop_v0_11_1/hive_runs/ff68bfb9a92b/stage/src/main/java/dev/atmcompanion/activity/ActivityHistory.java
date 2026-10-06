package dev.atmcompanion.activity;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.List;
import java.util.Objects;

/** Bounded, oldest-to-newest activity history. */
public final class ActivityHistory {
    private final int capacity;
    private final Deque<ActivityEvent> events = new ArrayDeque<>();

    public ActivityHistory(int capacity) {
        if (capacity < 1 || capacity > 256) {
            throw new IllegalArgumentException("capacity must be between 1 and 256");
        }
        this.capacity = capacity;
    }

    public synchronized void append(ActivityEvent event) {
        events.addLast(Objects.requireNonNull(event, "event"));
        while (events.size() > capacity) {
            events.removeFirst();
        }
    }

    public synchronized List<ActivityEvent> recent() {
        return Collections.unmodifiableList(new ArrayList<>(events));
    }

    /** Returns a detached summary of the currently retained events. */
    public ActivitySummary summary() {
        return ActivitySummary.from(recent());
    }

    public synchronized int size() {
        return events.size();
    }

    public synchronized void clear() {
        events.clear();
    }
}
