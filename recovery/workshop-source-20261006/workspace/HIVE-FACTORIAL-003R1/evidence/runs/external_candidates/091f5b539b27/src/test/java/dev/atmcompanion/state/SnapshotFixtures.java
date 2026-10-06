package dev.atmcompanion.state;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class SnapshotFixtures {
    private SnapshotFixtures() {}

    public static GameSnapshot empty() {
        return withInventory(List.of());
    }

    public static GameSnapshot populated() {
        return withInventory(List.of(
                new GameSnapshot.Item("minecraft:iron_ingot", 31, 0, false),
                new GameSnapshot.Item("mekanism:ingot_osmium", 12, 1, false),
                new GameSnapshot.Item("example_mod:tools/custom_pickaxe", 1, 8, true)));
    }

    public static GameSnapshot withInventory(List<GameSnapshot.Item> items) {
        var player = Observation.available(new GameSnapshot.Player(18, 20, 17, 2.5f, 23, "survival"));
        var location = Observation.available(new GameSnapshot.Location("minecraft:overworld", "minecraft:plains", 183.25, 72, -491.75));
        var inventory = Observation.available(new GameSnapshot.Inventory(items, 41, false));
        var equipment = Observation.available(new GameSnapshot.Equipment(null, null, null, null, null, null));
        var progression = Observation.available(new GameSnapshot.Progression(2, 1, 1, false, List.of(
                new GameSnapshot.Advancement("minecraft:story/root", true, 1, 1),
                new GameSnapshot.Advancement("example_mod:progression/late_game", false, 1, 3)), false));
        var mods = Observation.available(new GameSnapshot.Modpack(List.of(
                new GameSnapshot.Mod("minecraft", "1.21.1"),
                new GameSnapshot.Mod("neoforge", "21.1.251")), 2, false));
        var capabilities = capabilities(player, location, inventory, equipment, progression, mods);
        capabilities.put("quests", new Capability(CapabilityStatus.NOT_INTEGRATED, "Quest data has not been inspected"));
        capabilities.put("ae2_storage", new Capability(CapabilityStatus.NOT_INTEGRATED, "Storage data has not been inspected"));
        return new GameSnapshot(1, "2026-09-22T12:34:56Z", player, location, inventory, equipment, progression, mods, capabilities);
    }

    public static GameSnapshot unavailable() {
        Observation<GameSnapshot.Player> player = Observation.unavailable("Player unavailable");
        Observation<GameSnapshot.Location> location = Observation.unavailable("Player unavailable");
        Observation<GameSnapshot.Inventory> inventory = Observation.unavailable("Player unavailable");
        Observation<GameSnapshot.Equipment> equipment = Observation.unavailable("Player unavailable");
        Observation<GameSnapshot.Progression> progression = Observation.unavailable("Advancement API failed");
        Observation<GameSnapshot.Modpack> mods = Observation.unavailable("Mod list unavailable");
        return new GameSnapshot(1, "2026-09-22T12:34:56Z", player, location, inventory, equipment, progression, mods,
                capabilities(player, location, inventory, equipment, progression, mods));
    }

    public static GameSnapshot withCapabilities(GameSnapshot snapshot, Map<String, Capability> capabilities) {
        return new GameSnapshot(snapshot.schemaVersion(), snapshot.timestamp(), snapshot.player(), snapshot.location(),
                snapshot.inventory(), snapshot.equipment(), snapshot.progression(), snapshot.modpack(), capabilities);
    }

    private static Map<String, Capability> capabilities(Observation<?> player, Observation<?> location,
            Observation<?> inventory, Observation<?> equipment, Observation<?> progression, Observation<?> mods) {
        var capabilities = new LinkedHashMap<String, Capability>();
        capabilities.put("player", Capability.from(player));
        capabilities.put("location", Capability.from(location));
        capabilities.put("inventory", Capability.from(inventory));
        capabilities.put("equipment", Capability.from(equipment));
        capabilities.put("advancements", Capability.from(progression));
        capabilities.put("mods", Capability.from(mods));
        return capabilities;
    }
}
