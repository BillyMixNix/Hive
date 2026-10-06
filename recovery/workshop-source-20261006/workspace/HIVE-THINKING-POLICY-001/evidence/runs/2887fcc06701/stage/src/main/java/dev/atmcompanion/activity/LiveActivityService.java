package dev.atmcompanion.activity;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

public final class LiveActivityService {
    private final ConcurrentMap<String, ActivityTracker> playerTrackers = new ConcurrentHashMap<>();
    private final ConcurrentMap<String, ActivityHistory> playerHistory = new ConcurrentHashMap<>();

    public List<ActivityEvent> observe(String playerId, String timestamp, Map<String, Long> inventory) {
        if (playerId == null) throw new IllegalArgumentException("playerId must be non-null");
        if (timestamp == null) throw new IllegalArgumentException("timestamp must be non-null");
        if (inventory == null) throw new IllegalArgumentException("inventory must be non-null");

        // Create a defensive copy of the inventory
        Map<String, Long> inventoryCopy = new HashMap<>(inventory);

        // Get or create the player's ActivityTracker and ActivityHistory
        ActivityTracker tracker = playerTrackers.computeIfAbsent(playerId, id -> new ActivityTracker());
        ActivityHistory history = playerHistory.computeIfAbsent(playerId, id -> new ActivityHistory(64));

        // Observe the inventory and get events
        List<ActivityEvent> events = tracker.observe(playerId, timestamp, inventoryCopy);

        // Append events to the player's history
        for (ActivityEvent event : events) {
            history.append(event);
        }

        // Return an unmodifiable copy of the events
        return Collections.unmodifiableList(new ArrayList<>(events));
    }

    public void forget(String playerId) {
        if (playerId == null) throw new IllegalArgumentException("playerId must be non-null");
        
        // Remove the player's tracker and history
        playerTrackers.remove(playerId);
        playerHistory.remove(playerId);
    }

    public int trackedPlayers() {
        return playerTrackers.size();
    }
}
