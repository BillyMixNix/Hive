package dev.atmcompanion.state;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Stable raw sensor DTO. Contains no live Minecraft objects or account/session identifiers. */
public record GameSnapshot(
        int schemaVersion, String timestamp,
        Observation<Player> player, Observation<Location> location,
        Observation<Inventory> inventory, Observation<Equipment> equipment,
        Observation<Progression> progression, Observation<Modpack> modpack,
        Map<String, Capability> capabilities) {
    public static final int SCHEMA_VERSION = 1;
    public static final int MAX_INVENTORY_SLOTS = 64;
    public static final int MAX_MODS = 2048;
    public static final int MAX_ADVANCEMENTS = 256;
    public static final int MAX_ADVANCEMENTS_SCANNED = 20_000;
    public static final int MAX_CRITERIA_PER_ADVANCEMENT = 2048;

    public GameSnapshot {
        if (schemaVersion != SCHEMA_VERSION) throw new IllegalArgumentException("Unsupported snapshot schema " + schemaVersion);
        Instant.parse(Objects.requireNonNull(timestamp));
        Objects.requireNonNull(player); Objects.requireNonNull(location);
        Objects.requireNonNull(inventory); Objects.requireNonNull(equipment);
        Objects.requireNonNull(progression); Objects.requireNonNull(modpack);
        capabilities = Map.copyOf(Objects.requireNonNull(capabilities));
        requireCapability(capabilities, "player", player);
        requireCapability(capabilities, "location", location);
        requireCapability(capabilities, "inventory", inventory);
        requireCapability(capabilities, "equipment", equipment);
        requireCapability(capabilities, "advancements", progression);
        requireCapability(capabilities, "mods", modpack);
    }
    private static void requireCapability(Map<String, Capability> map, String key, Observation<?> observation) {
        if (!Capability.from(observation).equals(map.get(key))) {
            throw new IllegalArgumentException("Capability disagrees with observation: " + key);
        }
    }
    public record Player(float health, float maxHealth, int food, float saturation, int experienceLevel, String gameMode) {
        public Player {
            if (!Float.isFinite(health) || !Float.isFinite(maxHealth) || !Float.isFinite(saturation)) throw new IllegalArgumentException("Nonfinite player state");
            Objects.requireNonNull(gameMode);
        }
    }
    public record Location(String dimension, String biome, double x, double y, double z) {
        public Location {
            Objects.requireNonNull(dimension); Objects.requireNonNull(biome);
            if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)) throw new IllegalArgumentException("Nonfinite position");
        }
    }
    /** Slots 0..35 main inventory; 36..39 armor; 40 offhand. Equipment is a second view, not extra ownership. */
    public record Item(String item, int count, int slot, boolean hasNonDefaultComponents) {
        public Item {
            Objects.requireNonNull(item);
            if (!item.matches("[a-z0-9_.-]+:[a-z0-9/._-]+")) throw new IllegalArgumentException("Expected namespaced item ID");
            if (count < 1 || slot < 0) throw new IllegalArgumentException("Invalid occupied inventory slot");
        }
    }
    public record Inventory(List<Item> stacks, int totalSlots, boolean truncated) {
        public Inventory {
            stacks = List.copyOf(stacks);
            if (stacks.size() > MAX_INVENTORY_SLOTS || totalSlots < 0) throw new IllegalArgumentException("Inventory bounds exceeded");
        }
    }
    /** Null slot value means inspected and empty when the enclosing observation is available. */
    public record Equipment(Item mainHand, Item offHand, Item head, Item chest, Item legs, Item feet) {}
    public record Advancement(String id, boolean completed, int completedCriteria, int totalCriteria) {
        public Advancement {
            Objects.requireNonNull(id);
            if (completedCriteria < 0 || totalCriteria < completedCriteria) throw new IllegalArgumentException("Invalid criteria count");
        }
    }
    /** Counts cover scanned definitions, including recipe advancements. Truncated counts are lower bounds. */
    public record Progression(int scanned, int completed, int incomplete, boolean countsTruncated,
                              List<Advancement> advancements, boolean entriesTruncated) {
        public Progression {
            advancements = List.copyOf(advancements);
            if (scanned < 0 || completed < 0 || incomplete < 0 || completed + incomplete != scanned ||
                    scanned > MAX_ADVANCEMENTS_SCANNED || advancements.size() > MAX_ADVANCEMENTS) {
                throw new IllegalArgumentException("Invalid advancement bounds/counts");
            }
        }
    }
    public record Mod(String id, String version) {
        public Mod { Objects.requireNonNull(id); Objects.requireNonNull(version); }
    }
    /** Runtime mods do not establish the user's pack name/version; those remain unobserved. */
    public record Modpack(List<Mod> mods, int totalMods, boolean truncated) {
        public Modpack {
            mods = List.copyOf(mods);
            if (mods.size() > MAX_MODS || totalMods < mods.size()) throw new IllegalArgumentException("Invalid mod bounds");
        }
    }
}
