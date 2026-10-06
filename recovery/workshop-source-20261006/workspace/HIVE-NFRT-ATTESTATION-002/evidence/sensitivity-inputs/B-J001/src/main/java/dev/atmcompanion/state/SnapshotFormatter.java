package dev.atmcompanion.state;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class SnapshotFormatter {
    public static final int MAX_STATE_LINES = 16;
    public static final int MAX_LINE_CHARS = 240;
    private SnapshotFormatter() {}
    public static List<String> state(GameSnapshot snapshot) {
        List<String> lines = new ArrayList<>();
        lines.add("=== ATM COMPANION ===");
        if (snapshot.location().data() != null) {
            var location = snapshot.location().data();
            lines.add(location.dimension() + " | " + location.biome());
            lines.add(String.format(Locale.ROOT, "XYZ: %.1f / %.1f / %.1f", location.x(), location.y(), location.z()));
        } else lines.add("Location: " + snapshot.location().status().name().toLowerCase(Locale.ROOT));
        if (snapshot.player().data() != null) {
            var player = snapshot.player().data();
            lines.add(String.format(Locale.ROOT, "Health: %.1f/%.1f | Food: %d/20 | XP: %d | %s", player.health(), player.maxHealth(), player.food(), player.experienceLevel(), player.gameMode()));
        } else lines.add("Player: unavailable");
        if (snapshot.equipment().data() != null) lines.add("Main hand: " + itemText(snapshot.equipment().data().mainHand()));
        else lines.add("Equipment: unavailable");
        if (snapshot.inventory().data() != null) {
            var inventory = snapshot.inventory().data();
            lines.add("Inventory: " + inventory.stacks().size() + " occupied slots" + (inventory.truncated() ? " (partial)" : ""));
            inventory.stacks().stream().limit(3).forEach(item -> lines.add("  " + itemText(item)));
            if (inventory.stacks().size() > 3) lines.add("  + " + (inventory.stacks().size() - 3) + " other stacks");
        } else lines.add("Inventory: unavailable");
        if (snapshot.progression().data() != null) {
            var progression = snapshot.progression().data();
            lines.add("Advancements: " + progression.completed() + " completed / " + progression.scanned() + " inspected" + (progression.countsTruncated() ? " (partial)" : "") + "; includes recipe unlocks");
        } else lines.add("Advancements: unavailable");
        lines.add("Visibility details: /companion capabilities");
        return lines.stream().limit(MAX_STATE_LINES).map(SnapshotFormatter::boundLine).toList();
    }
    public static String boundLine(String line) {
        String safe = line.replaceAll("[\\p{Cntrl}\\u00a7]", "?");
        return safe.length() <= MAX_LINE_CHARS ? safe : safe.substring(0, MAX_LINE_CHARS - 3) + "...";
    }
    private static String itemText(GameSnapshot.Item item) {
        return item == null ? "empty" : item.count() + " x " + item.item();
    }
}

// NFRT source-sensitivity probe: no behavior change.
