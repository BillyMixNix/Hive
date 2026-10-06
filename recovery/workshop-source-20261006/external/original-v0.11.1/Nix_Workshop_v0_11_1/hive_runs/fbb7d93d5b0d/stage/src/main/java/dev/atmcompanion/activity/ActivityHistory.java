package dev.atmcompanion.activity;

import java.time.Instant;
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

    /**
     * Returns retained events in append order within [startInclusive, endExclusive).
     * Equal endpoints produce an empty window.
     *
     * @throws IllegalArgumentException if either endpoint is null or start is after end
     */
    public synchronized ActivityWindow between(Instant startInclusive, Instant endExclusive) {
        if (startInclusive == null || endExclusive == null) {
            throw new IllegalArgumentException("window endpoints must be non-null");
        }
        if (startInclusive.isAfter(endExclusive)) {
            throw new IllegalArgumentException("startInclusive must not be after endExclusive");
        }
        List<ActivityEvent> selected = new ArrayList<>();
        for (ActivityEvent event : events) {
            Instant timestamp = Instant.parse(event.timestamp());
            if (!timestamp.isBefore(startInclusive) && timestamp.isBefore(endExclusive)) {
                selected.add(event);
            }
        }
        return new ActivityWindow(selected, ActivitySummary.from(selected));
    }

    public synchronized int size() {
        return events.size();
    }

    public synchronized void clear() {
        events.clear();
    }
}
