package dev.atmcompanion.activity;

import dev.atmcompanion.state.GameSnapshot;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Adapts snapshot activity observations into bounded, command-friendly text. */
public final class ActivityCommandService {
    public static final int MAX_LINES = 66;

    private final LiveActivityService activity;

    public ActivityCommandService(LiveActivityService activity) {
        this.activity = Objects.requireNonNull(activity, "activity");
    }

    public List<String> observe(ServerPlayer player, GameSnapshot snapshot) {
        Objects.requireNonNull(player, "player");
        Objects.requireNonNull(snapshot, "snapshot");

        GameSnapshot.Inventory observed = snapshot.inventory().data();
        if (observed == null) {
            return List.of("Activity unavailable: inventory was not observed.");
        }

        Map<String, Long> inventory = new LinkedHashMap<>();
        for (GameSnapshot.Item stack : observed.stacks()) {
            inventory.merge(stack.item(), (long) stack.count(), Long::sum);
        }

        List<ActivityEvent> events = activity.observe(
                player.getGameProfile().getName(), snapshot.timestamp(), inventory);
        if (events.isEmpty()) {
            return List.of("No inventory changes since the previous activity check.");
        }

        List<String> lines = new ArrayList<>(Math.min(events.size(), MAX_LINES));
        for (ActivityEvent event : events) {
            if (lines.size() == MAX_LINES) break;
            String id = event.registryIds().isEmpty() ? "unknown" : event.registryIds().get(0);
            String quantity = event.quantity() == null ? "" : " x" + event.quantity();
            lines.add(event.type().name() + " " + id + quantity);
        }
        return List.copyOf(lines);
    }

    public String reset(String playerId) {
        if (playerId == null || playerId.trim().isEmpty()) {
            throw new IllegalArgumentException("playerId must be non-null and non-empty");
        }

        activity.forget(playerId);
        return "Activity history reset for " + playerId + ".";
    }
}
