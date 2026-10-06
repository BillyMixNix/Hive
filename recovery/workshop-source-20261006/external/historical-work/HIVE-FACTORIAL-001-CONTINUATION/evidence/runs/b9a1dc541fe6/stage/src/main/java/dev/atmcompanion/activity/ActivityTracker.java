package dev.atmcompanion.activity;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

public final class ActivityTracker {
    private final ConcurrentMap<String, Map<String, Long>> playerBaselines = new ConcurrentHashMap<>();
    private final int maxTrackedPlayers = 64;

    public List<ActivityEvent> observe(String playerId, String timestamp, Map<String, Long> inventory) {
        if (playerId == null) throw new IllegalArgumentException("playerId must be non-null");
        if (timestamp == null) throw new IllegalArgumentException("timestamp must be non-null");
        if (inventory == null) throw new IllegalArgumentException("inventory must be non-null");

        // Create a copy of the inventory to prevent modification after observation
        Map<String, Long> inventoryCopy = new HashMap<>(inventory);

        // Check if the player is already tracked and within the limit
        if (playerBaselines.size() >= maxTrackedPlayers && !playerBaselines.containsKey(playerId)) {
            throw new IllegalStateException("Cannot track more than 64 players");
        }

        // If the player has no baseline, this is their first observation
        if (!playerBaselines.containsKey(playerId)) {
            playerBaselines.put(playerId, inventoryCopy);
            return Collections.emptyList();
        }

        // Get the previous baseline for this player
        Map<String, Long> previousBaseline = playerBaselines.get(playerId);

        // Calculate the difference between the current inventory and the baseline
        List<ActivityEvent> events = ActivityDiffService.diff(timestamp, previousBaseline, inventoryCopy);

        // Update the player's baseline to the current inventory
        playerBaselines.put(playerId, inventoryCopy);

        return Collections.unmodifiableList(events);
    }

    public void forget(String playerId) {
        if (playerId == null) throw new IllegalArgumentException("playerId must be non-null");
        playerBaselines.remove(playerId);
    }

    public int trackedPlayers() {
        return playerBaselines.size();
    }
}
