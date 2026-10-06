package dev.atmcompanion.execution;

import com.mojang.logging.LogUtils;
import dev.atmcompanion.knowledge.NormalizedRecipe;
import dev.atmcompanion.state.Observation;
import dev.atmcompanion.state.SnapshotService;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.PriorityQueue;
import java.util.function.LongSupplier;
import net.minecraft.core.BlockPos;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.Tag;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.LockCode;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.AbstractCookingRecipe;
import net.minecraft.world.item.crafting.BlastingRecipe;
import net.minecraft.world.item.crafting.CampfireCookingRecipe;
import net.minecraft.world.item.crafting.Recipe;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.RecipeManager;
import net.minecraft.world.item.crafting.ShapedRecipe;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import net.minecraft.world.item.crafting.SingleRecipeInput;
import net.minecraft.world.item.crafting.SmeltingRecipe;
import net.minecraft.world.item.crafting.SmokingRecipe;
import net.minecraft.world.level.GameRules;
import net.minecraft.world.level.block.AbstractFurnaceBlock;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.CampfireBlock;
import net.minecraft.world.level.block.entity.AbstractFurnaceBlockEntity;
import net.minecraft.world.level.block.entity.BlastFurnaceBlockEntity;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.entity.CampfireBlockEntity;
import net.minecraft.world.level.block.entity.FurnaceBlockEntity;
import net.minecraft.world.level.block.entity.SmokerBlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import org.slf4j.Logger;

/** Explicit, observational server-thread requests. Sessions must never outlive their calling command. */
public final class StationService {
    public static final int RADIUS = 8, MAX_STATIONS = 32, MAX_DEEP = 8, MAX_PREDICATES = 4096;
    public static final long BUDGET_NANOS = 10_000_000L;
    private static final Logger LOGGER = LogUtils.getLogger();
    private final LongSupplier nanoTime;
    public StationService() { this(System::nanoTime); }
    /** Injectable clock makes cooperative-budget boundaries testable without sleeping or changing production limits. */
    public StationService(LongSupplier nanoTime) { this.nanoTime = Objects.requireNonNull(nanoTime); }
    public Session begin(ServerPlayer player) { return new Session(player); }
    public ExecutionContext scan(ServerPlayer player) { return begin(player).scan(); }
    public ExecutionContext capture(ServerPlayer player, NormalizedRecipe recipe, Map<String, Long> reservedMaterials) {
        return begin(player).capture(recipe, reservedMaterials);
    }

    public final class Session {
        private final ServerPlayer player;
        private final ServerLevel level;
        private final RecipeManager recipeManager;
        private final long gameTime, began;
        private final String timestamp;
        private final List<ItemStack> inventory = new ArrayList<>();
        private final List<Nearby> nearby;
        private final Map<BlockPos, Raw> inspected = new HashMap<>();
        private final Map<String, Observation<Integer>> playerBurnTimes = new HashMap<>();
        private final Map<String, Observation<Boolean>> uniqueMatches = new HashMap<>();
        private int scanned, loaded, unloaded, discovered, deep, predicates;
        private boolean budgetExceeded;

        private Session(ServerPlayer player) {
            SnapshotService.requireServerThread(player);
            this.player = player; this.level = player.serverLevel(); this.recipeManager = level.getRecipeManager();
            gameTime = player.serverLevel().getGameTime(); timestamp = Instant.now().toString(); began = nanoTime.getAsLong();
            for (int i = 0; i < 36; i++) inventory.add(player.getInventory().getItem(i).copy());
            nearby = discover();
        }
        public ExecutionContext scan() {
            requireCurrent();
            return context(Observation.unavailable("No selected operation; nearby discovery only"), null, ItemStack.EMPTY, Map.of());
        }
        public ExecutionContext capture(NormalizedRecipe recipe, Map<String, Long> reservedMaterials) {
            return capture(recipe, reservedMaterials, -1);
        }
        /** selectedInputSlot is the planner's actual main-inventory allocation; -1 requests the first live matching stack. */
        public ExecutionContext capture(NormalizedRecipe recipe, Map<String, Long> reservedMaterials, int selectedInputSlot) {
            requireCurrent(); Objects.requireNonNull(recipe); validateReservations(reservedMaterials);
            if (selectedInputSlot < -1 || selectedInputSlot >= 36) throw new IllegalArgumentException("Input slot outside main inventory");
            if (!player.isAlive() || player.isSpectator())
                return context(Observation.unavailable("A dead or spectator player cannot perform the selected operation"), null, ItemStack.EMPTY, reservedMaterials);
            try {
                RecipeHolder<?> holder = recipeManager.byKey(ResourceLocation.parse(recipe.id())).orElse(null);
                if (holder == null) return context(Observation.unavailable("Recipe no longer exists"), null, ItemStack.EMPTY, reservedMaterials);
                Recipe<?> live = holder.value(); String kind = recipeKind(live);
                if (kind == null || !recipe.dependencySupported())
                    return context(Observation.unavailable("Execution supports only normalized, fixed vanilla crafting/cooking recipes"), null, ItemStack.EMPTY, reservedMaterials);
                // Vanilla crafting menus and campfire completion both suppress outputs disabled by the world's feature flags.
                if ((kind.equals("crafting") || kind.equals("campfire"))
                        && !live.getResultItem(player.registryAccess()).isItemEnabled(player.serverLevel().enabledFeatures()))
                    return context(Observation.unavailable("The selected output is disabled by the current world's feature flags"), null, ItemStack.EMPTY, reservedMaterials);
                Observation<Boolean> unlock = kind.equals("crafting")
                        ? Observation.available(!player.serverLevel().getGameRules().getBoolean(GameRules.RULE_LIMITED_CRAFTING)
                            || live.isSpecial() || player.getRecipeBook().contains(holder))
                        : Observation.available(true);
                ItemStack input = ItemStack.EMPTY; int inputSlot = -1;
                Observation<Boolean> inputMatches = Observation.unavailable("Not applicable to crafting; material allocation is assessed separately");
                Observation<Boolean> unique = Observation.unavailable("Not applicable to crafting");
                Observation<Integer> duration = Observation.unavailable("Not a cooking operation");
                if (live instanceof AbstractCookingRecipe cooking) {
                    int first = selectedInputSlot < 0 ? 0 : selectedInputSlot;
                    int last = selectedInputSlot < 0 ? 36 : selectedInputSlot + 1;
                    boolean complete = true;
                    for (int slot = first; slot < last; slot++) {
                        if (!predicateAvailable()) { complete = false; break; }
                        ItemStack candidate = inventory.get(slot);
                        if (!candidate.isEmpty() && cooking.matches(new SingleRecipeInput(candidate), player.serverLevel())) {
                            input = candidate.copyWithCount(1); inputSlot = slot; break;
                        }
                    }
                    inputMatches = inputSlot >= 0 ? Observation.available(true) : complete ? Observation.available(false)
                            : Observation.unavailable("Input predicate/time budget reached");
                    if (cooking.getCookingTime() > 0) duration = Observation.available(cooking.getCookingTime());
                    else duration = Observation.unavailable("Runtime cooking duration is not positive");
                    if (!input.isEmpty()) unique = unique(cooking, input, inputSlot);
                    else unique = Observation.unavailable("No selected matching player input; recipe selection is unknown");
                }
                var facts = new ExecutionContext.Operation(recipe.id(), kind.equals("crafting") ? "crafting" : "cooking", kind,
                        kind.equals("crafting") && live.canCraftInDimensions(2, 2), kind.equals("crafting") && live.canCraftInDimensions(3, 3),
                        unlock, duration, unique, inputMatches, inputSlot, inputSlot < 0 ? null : itemId(input));
                return context(Observation.available(facts), live instanceof AbstractCookingRecipe c ? c : null, input, reservedMaterials);
            } catch (RuntimeException | LinkageError failure) {
                LOGGER.warn("ATM Companion execution observation failed for recipe {}", recipe.id(), failure);
                return context(Observation.unavailable("Recipe observation failed; see server log"), null, ItemStack.EMPTY, reservedMaterials);
            }
        }
        private void requireCurrent() {
            SnapshotService.requireServerThread(player);
            if (player.serverLevel() != level || level.getRecipeManager() != recipeManager || level.getGameTime() != gameTime)
                throw new IllegalStateException("Execution session is stale; capture a new command snapshot");
            for (int slot = 0; slot < 36; slot++) if (!ItemStack.matches(inventory.get(slot), player.getInventory().getItem(slot)))
                throw new IllegalStateException("Player inventory changed; capture a new command snapshot");
        }
        private boolean timeAvailable() {
            if (nanoTime.getAsLong() - began >= BUDGET_NANOS) budgetExceeded = true;
            return !budgetExceeded;
        }
        private boolean predicateAvailable() {
            if (!timeAvailable()) return false;
            if (predicates >= MAX_PREDICATES) return false;
            predicates++; return true;
        }
        private List<Nearby> discover() {
            Comparator<Nearby> order = Comparator.comparingDouble(Nearby::distance).thenComparingInt(n -> n.pos.getX())
                    .thenComparingInt(n -> n.pos.getY()).thenComparingInt(n -> n.pos.getZ());
            PriorityQueue<Nearby> nearest = new PriorityQueue<>(MAX_STATIONS, order.reversed());
            Map<Long, LevelChunk> chunks = new HashMap<>();
            BlockPos center = player.blockPosition();
            // Shell order prioritizes nearby evidence even when the cooperative budget stops the scan.
            outer: for (int shell = 0; shell <= RADIUS; shell++) for (int dx = -shell; dx <= shell; dx++)
                for (int dy = -shell; dy <= shell; dy++) for (int dz = -shell; dz <= shell; dz++) {
                    if (Math.max(Math.abs(dx), Math.max(Math.abs(dy), Math.abs(dz))) != shell) continue;
                    if (!timeAvailable()) break outer;
                    BlockPos pos = center.offset(dx, dy, dz); scanned++;
                    if (player.serverLevel().isOutsideBuildHeight(pos)) { loaded++; continue; }
                    int cx = pos.getX() >> 4, cz = pos.getZ() >> 4;
                    long key = ((long) cx << 32) ^ (cz & 0xffffffffL);
                    if (!chunks.containsKey(key)) chunks.put(key, player.serverLevel().getChunkSource().getChunkNow(cx, cz));
                    LevelChunk chunk = chunks.get(key);
                    if (chunk == null) { unloaded++; continue; }
                    loaded++;
                    BlockState state = chunk.getBlockState(pos); String kind = stationKind(state);
                    if (kind == null) continue;
                    discovered++;
                    Nearby station = new Nearby(pos, state, kind, player.distanceToSqr(pos.getX() + .5, pos.getY() + .5, pos.getZ() + .5),
                            chunk.getBlockEntities().get(pos));
                    if (nearest.size() < MAX_STATIONS) nearest.add(station);
                    else if (order.compare(station, nearest.peek()) < 0) { nearest.remove(); nearest.add(station); }
                }
            return nearest.stream().sorted(order).toList();
        }
        private ExecutionContext context(Observation<ExecutionContext.Operation> operation, AbstractCookingRecipe cooking,
                                         ItemStack selectedInput, Map<String, Long> reserved) {
            int selectedSlot = operation.data() == null ? -1 : operation.data().selectedInputSlot();
            var fuel = cooking == null || recipeKind(cooking).equals("campfire") ? List.<ExecutionContext.FuelSlot>of() : fuels(cooking, reserved, selectedSlot);
            List<ExecutionContext.Station> stations = new ArrayList<>();
            for (Nearby n : nearby) {
                boolean compatible = operation.data() != null && operation.data().stationKind().equals(n.kind);
                Raw raw = inspected.get(n.pos);
                if (compatible && raw == null && deep < MAX_DEEP && timeAvailable()) {
                    deep++; raw = inspect(n); inspected.put(n.pos, raw);
                }
                Observation<Boolean> lock = n.kind.equals("crafting") ? Observation.available(true)
                        : raw == null ? Observation.unavailable("Station has not received bounded detailed inspection") : raw.lock;
                Observation<ExecutionContext.Details> details = raw == null ? Observation.unavailable("Not inspected for this operation or inspection budget reached")
                        : raw.stacks == null ? Observation.unavailable(raw.failure)
                        : details(n, raw, compatible ? cooking : null, compatible ? selectedInput : ItemStack.EMPTY, fuel);
                stations.add(new ExecutionContext.Station(BuiltInRegistries.BLOCK.getKey(n.state.getBlock()).toString(), n.kind,
                        n.pos.getX(), n.pos.getY(), n.pos.getZ(), n.distance, player.canInteractWithBlock(n.pos, 0),
                        player.serverLevel().mayInteract(player, n.pos), lock, details));
            }
            List<String> limitations = List.of("Nearby stations and their contents are observations, not player-owned material resources.",
                    "Vanilla distance, lock, spawn protection and world border do not establish modded claim permissions, line of sight or a safe path.",
                    "Modded interaction permissions are unverified; no interaction event or world mutation is performed.",
                    "Only exact vanilla workstation blocks and block-entity classes are inspected. Discovery is limited to the shown cube and loaded chunks.",
                    "The 10 ms budget is cooperative; one recipe predicate, fuel hook or vanilla serialization call cannot be interrupted.",
                    "Cooking timing snapshots whitelist numeric fields only; raw NBT, names, locks and attachments are never exported.");
            return new ExecutionContext(1, timestamp, player.serverLevel().dimension().location().toString(),
                    new ExecutionContext.Scan(RADIUS, 4913, scanned, loaded, unloaded, discovered, discovered > MAX_STATIONS,
                            budgetExceeded, deep, predicates), stations, operation, fuel, limitations);
        }
        private Raw inspect(Nearby n) {
            try {
                if (n.kind.equals("crafting")) return new Raw(Observation.available(true), List.of(), Observation.unavailable("Crafting table has no cooking timers"), "");
                if (!expectedEntity(n)) return new Raw(Observation.unavailable("Expected vanilla block entity is absent, uninitialized or replaced"), null, null,
                        "Expected vanilla block entity is absent, uninitialized or replaced");
                Observation<Boolean> lock = Observation.available(true);
                if (n.entity instanceof AbstractFurnaceBlockEntity furnace) {
                    LockCode code = furnace.collectComponents().getOrDefault(DataComponents.LOCK, LockCode.NO_LOCK);
                    lock = Observation.available(code.unlocksWith(player.getMainHandItem()));
                    if (!lock.data()) return new Raw(lock, null, null, "Vanilla lock prevents inventory/timer inspection");
                    List<ItemStack> items = new ArrayList<>();
                    for (int i = 0; i < 3; i++) items.add(furnace.getItem(i).copy());
                    return new Raw(lock, List.copyOf(items), timers(furnace, false), "");
                }
                CampfireBlockEntity campfire = (CampfireBlockEntity) n.entity;
                if (campfire.getItems().size() != 4) throw new IllegalStateException("Campfire inventory shape changed");
                return new Raw(lock, campfire.getItems().stream().map(ItemStack::copy).toList(), timers(campfire, true), "");
            } catch (RuntimeException | LinkageError failure) {
                LOGGER.warn("ATM Companion vanilla station inspection failed for {}", n.kind, failure);
                return new Raw(Observation.unavailable("Station inspection failed; see server log"), null, null, "Station inspection failed; see server log");
            }
        }
        private Observation<ExecutionContext.Timers> timers(BlockEntity entity, boolean campfire) {
            if (!timeAvailable()) return Observation.unavailable("Timing inspection time budget reached");
            try { return readTimers(entity.saveCustomOnly(player.registryAccess()), campfire); }
            catch (RuntimeException | LinkageError failure) {
                LOGGER.warn("ATM Companion vanilla timing snapshot failed", failure);
                return Observation.unavailable("Vanilla timing serialization failed; see server log");
            }
        }
        private Observation<ExecutionContext.Details> details(Nearby n, Raw raw, AbstractCookingRecipe cooking,
                                                               ItemStack selectedInput, List<ExecutionContext.FuelSlot> fuel) {
            List<ExecutionContext.Stack> stacks = new ArrayList<>();
            for (int i = 0; i < raw.stacks.size(); i++) {
                ItemStack item = raw.stacks.get(i);
                stacks.add(new ExecutionContext.Stack(i, item.isEmpty() ? null : itemId(item), item.getCount(), !item.isEmpty() && !item.getComponentsPatch().isEmpty()));
            }
            boolean campfire = n.kind.equals("campfire");
            boolean lit = !n.kind.equals("crafting") && n.state.getValue(campfire ? CampfireBlock.LIT : AbstractFurnaceBlock.LIT);
            boolean waterlogged = campfire && n.state.getValue(CampfireBlock.WATERLOGGED);
            int free = campfire ? (int) raw.stacks.stream().filter(ItemStack::isEmpty).count() : 0;
            Observation<Boolean> input = Observation.unavailable("No selected matching cooking input");
            Observation<Boolean> output = Observation.unavailable("Output acceptance is not applicable or was not checked");
            Observation<Integer> burn = Observation.unavailable("No selected furnace operation");
            List<Integer> compatibleFuel = new ArrayList<>();
            if (cooking != null && !selectedInput.isEmpty()) {
                if (campfire) {
                    input = Observation.available(free > 0); output = Observation.available(true);
                    burn = Observation.unavailable("Campfires do not consume per-operation fuel; results drop into the world");
                } else {
                    ItemStack present = raw.stacks.get(0);
                    input = Observation.available(present.isEmpty() || (ItemStack.isSameItemSameComponents(present, selectedInput)
                            && present.getCount() < Math.min(present.getMaxStackSize(), ((AbstractFurnaceBlockEntity) n.entity).getMaxStackSize())));
                    if (timeAvailable()) {
                        try {
                            ItemStack result = cooking.assemble(new SingleRecipeInput(selectedInput), player.registryAccess());
                            ItemStack existing = raw.stacks.get(2);
                            int outputCapacity = Math.min(result.getMaxStackSize(), ((AbstractFurnaceBlockEntity) n.entity).getMaxStackSize());
                            output = Observation.available(!result.isEmpty() && result.getCount() <= outputCapacity && (existing.isEmpty()
                                    || (ItemStack.isSameItemSameComponents(existing, result)
                                    && (long) existing.getCount() + result.getCount() <= Math.min(existing.getMaxStackSize(), ((AbstractFurnaceBlockEntity) n.entity).getMaxStackSize()))));
                        } catch (RuntimeException | LinkageError failure) {
                            LOGGER.warn("ATM Companion cooking output inspection failed", failure);
                            output = Observation.unavailable("Output inspection failed; see server log");
                        }
                    } else output = Observation.unavailable("Output inspection time budget reached");
                    burn = burn(raw.stacks.get(1), cooking, "station:" + n.pos.asLong());
                    ItemStack currentFuel = raw.stacks.get(1);
                    for (var option : fuel) if (currentFuel.isEmpty() || (ItemStack.isSameItemSameComponents(currentFuel, inventory.get(option.slot()))
                            && currentFuel.getCount() < Math.min(currentFuel.getMaxStackSize(), ((AbstractFurnaceBlockEntity) n.entity).getMaxStackSize()))) compatibleFuel.add(option.slot());
                }
            }
            return Observation.available(new ExecutionContext.Details(stacks, lit, waterlogged, raw.timers, input, output, burn, free, compatibleFuel));
        }
        private List<ExecutionContext.FuelSlot> fuels(AbstractCookingRecipe cooking, Map<String, Long> reserved, int selectedInputSlot) {
            Map<String, Long> remaining = new HashMap<>(reserved);
            // Preserve the actual selected cooking input, including its component variant, before other same-ID stacks.
            if (selectedInputSlot >= 0) {
                String selectedId = itemId(inventory.get(selectedInputSlot));
                remaining.put(selectedId, Math.max(0L, remaining.getOrDefault(selectedId, 0L) - 1));
            }
            List<ExecutionContext.FuelSlot> result = new ArrayList<>();
            for (int slot = 0; slot < inventory.size(); slot++) {
                ItemStack stack = inventory.get(slot); if (stack.isEmpty()) continue;
                String id = itemId(stack); long needed = remaining.getOrDefault(id, 0L);
                int selectedReservation = slot == selectedInputSlot ? 1 : 0;
                int additional = (int) Math.min(stack.getCount() - selectedReservation, needed);
                int held = selectedReservation + additional; remaining.put(id, needed - additional);
                result.add(new ExecutionContext.FuelSlot(slot, id, stack.getCount(), stack.getCount() - held,
                        burn(stack, cooking, "player:" + slot), !stack.getComponentsPatch().isEmpty()));
            }
            return List.copyOf(result);
        }
        private Observation<Integer> burn(ItemStack stack, AbstractCookingRecipe cooking, String source) {
            if (stack.isEmpty()) return Observation.available(0);
            String key = recipeKind(cooking) + ":" + source;
            if (playerBurnTimes.containsKey(key)) return playerBurnTimes.get(key);
            if (!timeAvailable()) return Observation.unavailable("Fuel observation time budget reached");
            Observation<Integer> result;
            try {
                int ticks = stack.getBurnTime(cooking.getType());
                if (cooking.getClass() == BlastingRecipe.class || cooking.getClass() == SmokingRecipe.class) ticks /= 2;
                result = ticks >= 0 ? Observation.available(ticks) : Observation.unavailable("Fuel hook returned a negative duration");
            } catch (RuntimeException | LinkageError failure) {
                LOGGER.warn("ATM Companion fuel observation failed for {}", itemId(stack), failure);
                result = Observation.unavailable("Fuel hook failed; see server log");
            }
            playerBurnTimes.put(key, result); return result;
        }
        @SuppressWarnings("unchecked")
        private Observation<Boolean> unique(AbstractCookingRecipe selected, ItemStack input, int slot) {
            String key = recipeKind(selected) + ":" + slot;
            if (uniqueMatches.containsKey(key)) return uniqueMatches.get(key);
            int matches = 0;
            try {
                for (RecipeHolder<?> holder : recipeManager.getRecipes()) {
                    if (!timeAvailable()) return Observation.unavailable("Cooking recipe selection time budget reached");
                    if (holder.value().getType() != selected.getType()) continue;
                    if (!predicateAvailable()) return Observation.unavailable("Cooking recipe selection predicate budget reached");
                    if (((Recipe<SingleRecipeInput>) holder.value()).matches(new SingleRecipeInput(input), player.serverLevel()) && ++matches > 1) {
                        var answer = Observation.available(false); uniqueMatches.put(key, answer); return answer;
                    }
                }
                var answer = Observation.available(matches == 1); uniqueMatches.put(key, answer); return answer;
            } catch (RuntimeException | LinkageError failure) {
                LOGGER.warn("ATM Companion cooking recipe uniqueness inspection failed", failure);
                return Observation.unavailable("A runtime recipe predicate failed; station recipe selection is unknown");
            }
        }
    }

    /** Version-specific numeric whitelist: never copies raw NBT or accepts absent numeric tags as zero. */
    public static Observation<ExecutionContext.Timers> readTimers(CompoundTag tag, boolean campfire) {
        if (campfire) {
            if (!tag.contains("CookingTimes", Tag.TAG_INT_ARRAY) || !tag.contains("CookingTotalTimes", Tag.TAG_INT_ARRAY))
                return Observation.unavailable("Campfire timing arrays missing or wrong type");
            int[] progress = tag.getIntArray("CookingTimes"), totals = tag.getIntArray("CookingTotalTimes");
            if (progress.length != 4 || totals.length != 4 || Arrays.stream(progress).anyMatch(v -> v < 0) || Arrays.stream(totals).anyMatch(v -> v < 0))
                return Observation.unavailable("Campfire timing arrays malformed");
            return Observation.available(new ExecutionContext.Timers(0, 0, 0, Arrays.stream(progress).boxed().toList(), Arrays.stream(totals).boxed().toList()));
        }
        if (!tag.contains("BurnTime", Tag.TAG_INT) || !tag.contains("CookTime", Tag.TAG_INT) || !tag.contains("CookTimeTotal", Tag.TAG_INT))
            return Observation.unavailable("Furnace timing values missing or wrong type");
        int burn = tag.getInt("BurnTime"), progress = tag.getInt("CookTime"), total = tag.getInt("CookTimeTotal");
        if (burn < 0 || progress < 0 || total < 0) return Observation.unavailable("Furnace timing values negative");
        return Observation.available(new ExecutionContext.Timers(burn, progress, total, List.of(), List.of()));
    }
    private static void validateReservations(Map<String, Long> reserved) {
        Objects.requireNonNull(reserved);
        if (reserved.size() > 256) throw new IllegalArgumentException("Too many reserved material identities");
        reserved.forEach((id, count) -> {
            if (id == null || ResourceLocation.tryParse(id) == null || count == null || count < 0 || count > 1_000_000)
                throw new IllegalArgumentException("Invalid reserved material amount");
        });
    }
    private static String itemId(ItemStack item) { return BuiltInRegistries.ITEM.getKey(item.getItem()).toString(); }
    private static String recipeKind(Recipe<?> recipe) {
        Class<?> type = recipe.getClass();
        if (type == ShapedRecipe.class || type == ShapelessRecipe.class) return "crafting";
        if (type == SmeltingRecipe.class) return "furnace";
        if (type == BlastingRecipe.class) return "blast_furnace";
        if (type == SmokingRecipe.class) return "smoker";
        if (type == CampfireCookingRecipe.class) return "campfire";
        return null;
    }
    private static String stationKind(BlockState state) {
        if (state.is(Blocks.CRAFTING_TABLE)) return "crafting";
        if (state.is(Blocks.FURNACE)) return "furnace";
        if (state.is(Blocks.BLAST_FURNACE)) return "blast_furnace";
        if (state.is(Blocks.SMOKER)) return "smoker";
        if (state.is(Blocks.CAMPFIRE) || state.is(Blocks.SOUL_CAMPFIRE)) return "campfire";
        return null;
    }
    private static boolean expectedEntity(Nearby n) {
        if (n.entity == null || n.entity.isRemoved()) return false;
        Class<?> actual = n.entity.getClass();
        return switch (n.kind) {
            case "furnace" -> actual == FurnaceBlockEntity.class;
            case "blast_furnace" -> actual == BlastFurnaceBlockEntity.class;
            case "smoker" -> actual == SmokerBlockEntity.class;
            case "campfire" -> actual == CampfireBlockEntity.class;
            default -> false;
        };
    }
    private record Nearby(BlockPos pos, BlockState state, String kind, double distance, BlockEntity entity) {}
    private record Raw(Observation<Boolean> lock, List<ItemStack> stacks, Observation<ExecutionContext.Timers> timers, String failure) {}
}
