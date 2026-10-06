package dev.atmcompanion.planning;

import com.mojang.logging.LogUtils;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import net.minecraft.core.HolderLookup;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.Tag;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.level.saveddata.SavedData;

/** Per-player goals in the world's standard overworld SavedData, shared across dimensions. */
public final class GoalSavedData extends SavedData {
    public static final int MAX_PLAYERS = 4096;
    private final Map<UUID, Goal> goals = new HashMap<>();
    public static GoalSavedData get(MinecraftServer server) {
        if (!server.isSameThread()) throw new IllegalStateException("Goals require the server thread");
        return server.overworld().getDataStorage().computeIfAbsent(new Factory<>(GoalSavedData::new, GoalSavedData::load), "atm_companion_goals");
    }
    public Goal goal(UUID player) { return goals.get(player); }
    public void set(UUID player, Goal goal) {
        java.util.Objects.requireNonNull(player); java.util.Objects.requireNonNull(goal);
        if (!goals.containsKey(player) && goals.size() >= MAX_PLAYERS) throw new IllegalStateException("Persistent goal player limit reached");
        goals.put(player, goal); setDirty();
    }
    public boolean clear(UUID player) { boolean removed = goals.remove(player) != null; if (removed) setDirty(); return removed; }
    public static GoalSavedData load(CompoundTag tag, HolderLookup.Provider provider) {
        GoalSavedData result = new GoalSavedData();
        if (tag.getInt("schemaVersion") != 1) {
            LogUtils.getLogger().warn("ATM Companion goals: unsupported/missing saved schema; no goals loaded");
            return result;
        }
        ListTag entries = tag.getList("goals", Tag.TAG_COMPOUND);
        int invalid = 0;
        for (int i = 0; i < Math.min(entries.size(), MAX_PLAYERS); i++) {
            CompoundTag entry = entries.getCompound(i);
            try { result.goals.put(entry.getUUID("player"), new Goal(entry.getString("item"), entry.getInt("quantity"))); }
            catch (RuntimeException exception) { invalid++; }
        }
        if (invalid > 0 || entries.size() > MAX_PLAYERS)
            LogUtils.getLogger().warn("ATM Companion goals: ignored {} malformed entries; source entries={}, limit={}", invalid, entries.size(), MAX_PLAYERS);
        return result;
    }
    @Override public CompoundTag save(CompoundTag tag, HolderLookup.Provider provider) {
        tag.putInt("schemaVersion", 1);
        ListTag entries = new ListTag();
        goals.entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(entry -> {
            CompoundTag value = new CompoundTag();
            value.putUUID("player", entry.getKey()); value.putString("item", entry.getValue().item());
            value.putInt("quantity", entry.getValue().quantity()); entries.add(value);
        });
        tag.put("goals", entries);
        return tag;
    }
}
