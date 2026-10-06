package dev.atmcompanion.state;

import com.mojang.logging.LogUtils;
import dev.atmcompanion.integration.IntegrationRegistry;
import dev.atmcompanion.integration.quest.QuestService;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import net.minecraft.advancements.AdvancementHolder;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.entity.EquipmentSlot;
import net.minecraft.world.item.ItemStack;
import net.neoforged.fml.ModList;
import org.slf4j.Logger;

/** Explicit, bounded logical-server capture. Never runs on a tick or background thread. */
public final class SnapshotService {
    private static final Logger LOGGER = LogUtils.getLogger();
    private final IntegrationRegistry integrations = new IntegrationRegistry(
            id -> ModList.get().isLoaded(id), message -> LOGGER.warn("{}", message));
    private final QuestService quests = new QuestService();

    public GameSnapshot capture(ServerPlayer player) {
        requireServerThread(player);
        Observation<GameSnapshot.Player> playerState = observe("player", () -> new GameSnapshot.Player(
                player.getHealth(), player.getMaxHealth(), player.getFoodData().getFoodLevel(),
                player.getFoodData().getSaturationLevel(), player.experienceLevel,
                player.gameMode.getGameModeForPlayer().getName()));
        Observation<GameSnapshot.Location> location = observe("location", () -> new GameSnapshot.Location(
                player.serverLevel().dimension().location().toString(),
                player.serverLevel().getBiome(player.blockPosition()).unwrapKey()
                        .orElseThrow(() -> new IllegalStateException("Biome has no registry key")).location().toString(),
                player.getX(), player.getY(), player.getZ()));
        Observation<GameSnapshot.Inventory> inventory = observe("inventory", () -> inventory(player));
        Observation<GameSnapshot.Equipment> equipment = observe("equipment", () -> new GameSnapshot.Equipment(
                item(player.getMainHandItem(), player.getInventory().selected), item(player.getOffhandItem(), 40),
                item(player.getItemBySlot(EquipmentSlot.HEAD), 39), item(player.getItemBySlot(EquipmentSlot.CHEST), 38),
                item(player.getItemBySlot(EquipmentSlot.LEGS), 37), item(player.getItemBySlot(EquipmentSlot.FEET), 36)));
        Observation<GameSnapshot.Progression> progression = player.isFakePlayer()
                ? Observation.unavailable("Synthetic players do not expose persistent advancement state")
                : observe("advancements", () -> advancements(player));
        Observation<GameSnapshot.Modpack> modpack = observe("mods", this::mods);
        Map<String, Capability> capabilities = new LinkedHashMap<>();
        capabilities.put("player", Capability.from(playerState));
        capabilities.put("location", Capability.from(location));
        capabilities.put("inventory", Capability.from(inventory));
        capabilities.put("equipment", Capability.from(equipment));
        capabilities.put("advancements", Capability.from(progression));
        capabilities.put("mods", Capability.from(modpack));
        try {
            var index = RuntimeKnowledge.get(player.getServer());
            capabilities.put("recipes", new Capability(CapabilityStatus.AVAILABLE,
                    "Runtime index generation " + index.generation() + "; " + index.stats().indexedRecipes() + " definitions; complete static coverage=" + index.complete() + "; per-recipe support and execution limits apply"));
        } catch (RuntimeException exception) {
            capabilities.put("recipes", new Capability(CapabilityStatus.UNAVAILABLE, "Runtime recipe index unavailable; wait for server startup/reload and inspect the server log"));
        }
        capabilities.put("nearby_environment", new Capability(CapabilityStatus.NOT_INTEGRATED, "General environment/resources not inspected; dimension/biome are in location, vanilla stations have a separate on-demand sensor"));
        capabilities.put("nearby_stations", new Capability(CapabilityStatus.AVAILABLE,
                "On-demand vanilla station sensor in stations/goal/next; not collected in this snapshot. Loaded radius-8 cube, bounded and partial; no ownership or modded access claim"));
        capabilities.put("quests", quests.capability(player));
        notIntegrated(capabilities, "ae2_storage", "ae2");
        notIntegrated(capabilities, "mekanism_machines", "mekanism");
        notIntegrated(capabilities, "jei", "jei");
        notIntegrated(capabilities, "emi", "emi");
        notIntegrated(capabilities, "sophisticated_storage", "sophisticatedstorage");
        notIntegrated(capabilities, "refined_storage", "refinedstorage");
        notIntegrated(capabilities, "mystical_agriculture", "mysticalagriculture");
        notIntegrated(capabilities, "productive_bees", "productivebees");
        capabilities.putAll(integrations.inspect());
        return new GameSnapshot(GameSnapshot.SCHEMA_VERSION, Instant.now().toString(), playerState, location,
                inventory, equipment, progression, modpack, capabilities);
    }
    public static void requireServerThread(ServerPlayer player) {
        if (player.getServer() == null || !player.getServer().isSameThread()) {
            throw new IllegalStateException("Snapshots and recipe queries must run on the logical server thread");
        }
    }
    private GameSnapshot.Inventory inventory(ServerPlayer player) {
        var inventory = player.getInventory();
        List<GameSnapshot.Item> stacks = new ArrayList<>();
        int count = Math.min(inventory.getContainerSize(), GameSnapshot.MAX_INVENTORY_SLOTS);
        for (int slot = 0; slot < count; slot++) {
            GameSnapshot.Item item = item(inventory.getItem(slot), slot);
            if (item != null) stacks.add(item);
        }
        return new GameSnapshot.Inventory(stacks, inventory.getContainerSize(), inventory.getContainerSize() > count);
    }
    private GameSnapshot.Item item(ItemStack stack, int slot) {
        if (stack.isEmpty()) return null;
        return new GameSnapshot.Item(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), stack.getCount(), slot,
                !stack.getComponentsPatch().isEmpty());
    }
    private GameSnapshot.Progression advancements(ServerPlayer player) {
        var all = player.getServer().getAdvancements().getAllAdvancements();
        int scanned = 0;
        int completed = 0;
        long started = System.nanoTime();
        List<GameSnapshot.Advancement> entries = new ArrayList<>();
        for (AdvancementHolder holder : all) {
            if (scanned >= GameSnapshot.MAX_ADVANCEMENTS_SCANNED || System.nanoTime() - started > 100_000_000L) break;
            if (holder.value().criteria().size() > GameSnapshot.MAX_CRITERIA_PER_ADVANCEMENT) {
                throw new IllegalStateException("Advancement " + holder.id() + " exceeds criterion inspection limit");
            }
            var progress = player.getAdvancements().getOrStartProgress(holder);
            scanned++;
            if (progress.isDone()) completed++;
            if (entries.size() < GameSnapshot.MAX_ADVANCEMENTS) {
                int completedCriteria = 0;
                for (String ignored : progress.getCompletedCriteria()) completedCriteria++;
                entries.add(new GameSnapshot.Advancement(holder.id().toString(), progress.isDone(), completedCriteria,
                        holder.value().criteria().size()));
            }
        }
        return new GameSnapshot.Progression(scanned, completed, scanned - completed, all.size() > scanned,
                entries, scanned > entries.size() || all.size() > scanned);
    }
    private GameSnapshot.Modpack mods() {
        var all = ModList.get().getMods();
        List<GameSnapshot.Mod> mods = all.stream().limit(GameSnapshot.MAX_MODS)
                .map(mod -> new GameSnapshot.Mod(mod.getModId(), boundedMetadata(mod.getVersion().toString())))
                .sorted(java.util.Comparator.comparing(GameSnapshot.Mod::id)).toList();
        return new GameSnapshot.Modpack(mods, all.size(), all.size() > mods.size());
    }
    private static String boundedMetadata(String value) {
        return value.length() <= 128 ? value : value.substring(0, 125) + "...";
    }
    private static void notIntegrated(Map<String, Capability> map, String capability, String mod) {
        boolean present = ModList.get().isLoaded(mod);
        map.put(capability, new Capability(CapabilityStatus.NOT_INTEGRATED,
                "Adapter not implemented; " + mod + (present ? " is installed" : " is not installed") + "; state was not inspected"));
    }
    private static <T> Observation<T> observe(String section, Supplier<T> operation) {
        try { return Observation.available(operation.get()); }
        catch (RuntimeException | LinkageError exception) {
            LOGGER.warn("ATM Companion could not observe section {}", section, exception);
            return Observation.unavailable("Capture failed: " + exception.getClass().getSimpleName() + "; see server log");
        }
    }
}

// JVM-triggering harmless negative-control edit.
