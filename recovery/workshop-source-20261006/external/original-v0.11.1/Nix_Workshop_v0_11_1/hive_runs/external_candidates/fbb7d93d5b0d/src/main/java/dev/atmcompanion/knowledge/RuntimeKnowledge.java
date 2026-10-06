package dev.atmcompanion.knowledge;

import com.mojang.logging.LogUtils;
import java.util.Collection;
import java.util.IdentityHashMap;
import java.util.Map;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.RecipeManager;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.OnDatapackSyncEvent;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStoppedEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import org.slf4j.Logger;

/** One immutable cache per server. Finite lifecycle jobs publish atomically; commands never scan recipes. */
public final class RuntimeKnowledge {
    public static final int STABILIZATION_TICKS = 20;
    public static final int MAX_AUTOMATIC_RESTARTS = 8;
    public static final int MAX_STABILIZATION_WAIT_TICKS = 1_200;
    private static final Logger LOGGER = LogUtils.getLogger();
    private static final Map<MinecraftServer, State> STATES = new IdentityHashMap<>();
    private static boolean installed;
    private RuntimeKnowledge() { }
    public static synchronized void install() {
        if (installed) return;
        installed = true;
        NeoForge.EVENT_BUS.addListener(RuntimeKnowledge::serverStarted);
        NeoForge.EVENT_BUS.addListener(RuntimeKnowledge::datapacksSynced);
        NeoForge.EVENT_BUS.addListener(RuntimeKnowledge::serverStopped);
        NeoForge.EVENT_BUS.addListener(RuntimeKnowledge::serverTick);
    }
    private static void serverStarted(ServerStartedEvent event) { scheduleSafely(event.getServer()); }
    private static void datapacksSynced(OnDatapackSyncEvent event) {
        // Null is the core resource/tag swap. Later mod listeners may still replace recipes; tick freshness recovers.
        // A player join alone does not rebuild, but a recipe-table change during that join does trigger recovery.
        if (event.getPlayer() == null) scheduleSafely(event.getPlayerList().getServer());
    }
    private static void serverStopped(ServerStoppedEvent event) {
        synchronized (STATES) { STATES.remove(event.getServer()); }
    }
    private static void serverTick(ServerTickEvent.Post event) { advance(event.getServer()); }
    private static void scheduleSafely(MinecraftServer server) {
        try { schedule(server); }
        catch (RuntimeException | LinkageError exception) {
            LOGGER.error("ATM Companion could not schedule recipe indexing", exception);
        }
    }
    /** Explicit lifecycle scheduling starts a new recovery episode; subsequent ticks do all extraction work. */
    public static long schedule(MinecraftServer server) {
        requireThread(server);
        State previous = state(server);
        State current = new State(previous == null ? 1 : previous.generation + 1);
        replace(server, current);
        try {
            start(current, server, source(server));
        } catch (RuntimeException | LinkageError exception) {
            fail(current, "Scheduling failed: " + exception.getClass().getSimpleName() + "; see server log");
            throw exception;
        }
        return current.generation;
    }
    /** One cooperative slice. Recovery debounce measures server ticks, never calls to this method. */
    public static void advance(MinecraftServer server) {
        requireThread(server);
        State current = state(server);
        if (current == null || current.phase.equals("failed")) return;
        if (waitingExpired(server, current)) return;
        try {
            Source observed = source(server);
            if (!same(current.source, observed)) {
                changed(server, current, observed);
                return;
            }
            if (current.phase.equals("recovering")) {
                if (stableTicks(server, current) >= STABILIZATION_TICKS) restart(server, current, observed);
                return;
            }
            RecipeIndexBuilder.Job job = current.job;
            if (job == null) return;
            job.advance();
            // A recipe callback can replace the table or schedule a new lifecycle generation mid-slice.
            if (state(server) != current || current.job != job || !current.phase.equals("building")) return;
            Source afterSlice = source(server);
            if (!same(current.source, afterSlice)) {
                changed(server, current, afterSlice);
                return;
            }
            current.lastProgress = job.progress();
            if (job.done()) {
                RecipeIndex result = job.result();
                synchronized (STATES) {
                    if (STATES.get(server) != current) return;
                    current.index = result;
                    current.job = null;
                    current.phase = "ready";
                    current.detail = "Completed bounded index; per-recipe and coverage limitations still apply";
                    current.automaticRestarts = 0;
                    current.observedChanges = 0;
                }
                LOGGER.info("ATM Companion published recipe index generation {} with {} definitions", current.generation, result.stats().indexedRecipes());
            }
        } catch (RuntimeException | LinkageError exception) {
            // Expected source changes use changed(); genuine extraction/scheduling errors do not auto-retry.
            if (state(server) != current) return;
            fail(current, "Index build failed: " + exception.getClass().getSimpleName() + "; see server log");
            LOGGER.error("ATM Companion recipe index generation {} failed; automatic retry disabled for this error", current.generation, exception);
        }
    }
    /** Explicit synchronous harness seam. It fails immediately if recovery would require future server ticks. */
    public static RecipeIndex rebuild(MinecraftServer server) {
        long generation = schedule(server);
        while (true) {
            BuildStatus progress = status(server);
            if (progress.generation() != generation) throw new IllegalStateException("Recipe index build was replaced by another generation");
            if (progress.state().equals("ready")) return get(server);
            if (!progress.state().equals("building")) throw new IllegalStateException(progress.detail());
            advance(server);
        }
    }
    public static RecipeIndex get(MinecraftServer server) {
        requireThread(server);
        State current = state(server);
        if (current == null) throw new IndexUnavailableException("Recipe index is unavailable; server lifecycle build has not started");
        observe(server, current);
        if (state(server) != current || current.index == null)
            throw new IndexUnavailableException(current.phase + ": " + detail(server, current));
        return current.index;
    }
    public static BuildStatus status(MinecraftServer server) {
        requireThread(server);
        State current = state(server);
        if (current == null) return new BuildStatus("unavailable", 0, "unavailable", 0, 0, 0, 0, 0, 0, 0, 0, 0,
                "Server lifecycle index is not available");
        observe(server, current);
        var progress = current.job == null ? current.lastProgress : current.job.progress();
        String phase = current.phase.equals("recovering") ? "stabilizing" : progress == null ? current.phase : progress.phase();
        return new BuildStatus(current.phase, current.generation, phase,
                progress == null ? current.source == null ? 0 : current.source.count : progress.totalDefinitions(),
                progress == null ? 0 : progress.visitedDefinitions(), progress == null ? 0 : progress.selectedDefinitions(),
                progress == null ? 0 : progress.normalizedDefinitions(), progress == null ? 0 : progress.lookupDefinitions(),
                progress == null ? 0 : progress.slices(), progress == null ? 0 : progress.activeMillis(),
                progress == null ? 0 : progress.elapsedMillis(), progress == null ? 0 : progress.maxSliceMillis(), detail(server, current));
    }
    /** Read-only freshness work may invalidate and begin waiting, but never starts/advances a build. */
    private static void observe(MinecraftServer server, State current) {
        if (current.phase.equals("failed")) return;
        if (waitingExpired(server, current)) return;
        try {
            Source observed = source(server);
            if (!same(current.source, observed)) changed(server, current, observed);
        } catch (RuntimeException | LinkageError exception) {
            fail(current, "Recipe source inspection failed: " + exception.getClass().getSimpleName() + "; see server log");
            LOGGER.error("ATM Companion recipe source inspection failed for generation {}; automatic retry disabled", current.generation, exception);
        }
    }
    private static void changed(MinecraftServer server, State current, Source observed) {
        if (state(server) != current || current.phase.equals("failed")) return;
        Source old = current.source;
        String reason = old == null || old.manager != observed.manager ? "manager replaced"
                : old.definitions != observed.definitions ? "definition table replaced" : "definition count changed";
        boolean alreadyWaiting = current.phase.equals("recovering");
        current.job = null; current.index = null; current.lastProgress = null;
        current.source = observed;
        current.observedChanges = Math.min(Integer.MAX_VALUE - 1, current.observedChanges) + 1;
        current.stableSinceTick = server.getTickCount();
        if (!alreadyWaiting) current.waitingSinceTick = current.stableSinceTick;
        if (current.automaticRestarts >= MAX_AUTOMATIC_RESTARTS) {
            fail(current, "Recipe definitions changed after " + MAX_AUTOMATIC_RESTARTS
                    + " automatic restart attempts without publication; automatic recovery stopped. Inspect recipe-changing mods, then complete /reload to retry.");
            LOGGER.warn("ATM Companion recipe index generation {} stopped automatic recovery: {} ({} -> {} definitions, {} automatic attempts)",
                    current.generation, reason, old == null ? 0 : old.count, observed.count, current.automaticRestarts);
            return;
        }
        current.phase = "recovering";
        current.detail = "Recipe source changed (" + reason + ", " + (old == null ? 0 : old.count) + " -> " + observed.count
                + " definitions); stale facts discarded";
        if (alreadyWaiting) LOGGER.debug("ATM Companion recipe source changed while stabilizing generation {}: {} ({} -> {} definitions, {} automatic attempts)",
                current.generation, reason, old == null ? 0 : old.count, observed.count, current.automaticRestarts);
        else LOGGER.warn("ATM Companion invalidated recipe index generation {}: {} ({} -> {} definitions); waiting {} unchanged server ticks before automatic rebuild, attempts {}/{}",
                current.generation, reason, old == null ? 0 : old.count, observed.count, STABILIZATION_TICKS,
                current.automaticRestarts, MAX_AUTOMATIC_RESTARTS);
    }
    private static void restart(MinecraftServer server, State previous, Source observed) {
        if (state(server) != previous) return;
        State replacement = new State(previous.generation + 1);
        replacement.automaticRestarts = previous.automaticRestarts + 1;
        replacement.observedChanges = previous.observedChanges;
        replace(server, replacement);
        try {
            start(replacement, server, observed);
            LOGGER.info("ATM Companion automatically restarting recipe index as generation {} after {} stable server ticks ({} definitions, attempt {}/{})",
                    replacement.generation, STABILIZATION_TICKS, observed.count, replacement.automaticRestarts, MAX_AUTOMATIC_RESTARTS);
        } catch (RuntimeException | LinkageError exception) {
            fail(replacement, "Automatic scheduling failed: " + exception.getClass().getSimpleName() + "; see server log");
            LOGGER.error("ATM Companion automatic recipe index scheduling failed for generation {}; further automatic retry disabled", replacement.generation, exception);
        }
    }
    private static void start(State current, MinecraftServer server, Source observed) {
        current.source = observed;
        current.job = RecipeIndexBuilder.start(server, current.generation, observed.definitions);
        current.phase = "building";
        current.detail = "Recipe knowledge is building; no previous-generation facts are exposed"
                + (current.automaticRestarts == 0 ? "" : "; automatic recovery attempt " + current.automaticRestarts + "/" + MAX_AUTOMATIC_RESTARTS);
    }
    private static int stableTicks(MinecraftServer server, State current) {
        // Integer subtraction also handles the server tick counter's normal signed wraparound.
        return Math.max(0, server.getTickCount() - current.stableSinceTick);
    }
    private static boolean waitingExpired(MinecraftServer server, State current) {
        if (!current.phase.equals("recovering") || server.getTickCount() - current.waitingSinceTick < MAX_STABILIZATION_WAIT_TICKS)
            return false;
        fail(current, "Recipe definitions did not stabilize within " + MAX_STABILIZATION_WAIT_TICKS
                + " server ticks; automatic recovery stopped. Inspect recipe-changing mods, then complete /reload to retry.");
        LOGGER.warn("ATM Companion recipe index generation {} stopped waiting after {} server ticks ({} definitions, {} observed source changes, {} automatic attempts)",
                current.generation, MAX_STABILIZATION_WAIT_TICKS, current.source == null ? 0 : current.source.count,
                current.observedChanges, current.automaticRestarts);
        return true;
    }
    private static String detail(MinecraftServer server, State current) {
        if (!current.phase.equals("recovering")) return current.detail;
        return current.detail + "; stabilizing " + Math.min(STABILIZATION_TICKS, stableTicks(server, current)) + "/" + STABILIZATION_TICKS
                + " server ticks; automatic attempts " + current.automaticRestarts + "/" + MAX_AUTOMATIC_RESTARTS
                + "; waiting " + Math.max(0, server.getTickCount() - current.waitingSinceTick) + "/" + MAX_STABILIZATION_WAIT_TICKS
                + " ticks; observed source changes " + current.observedChanges + ". Recovery advances on server ticks; /reload is not required.";
    }
    // MC 1.21.1 getRecipes() returns byName.values(); apply/replaceRecipes replace that ImmutableMap.
    // Guava 32.1.2 caches its values view. Identity detects same-count replacement without a scan.
    // Arbitrary mutation inside an existing recipe object remains outside this freshness guarantee.
    private static Source source(MinecraftServer server) {
        RecipeManager manager = server.getRecipeManager();
        var definitions = manager.getRecipes();
        return new Source(manager, definitions, definitions.size());
    }
    private static boolean same(Source first, Source second) {
        return first != null && first.manager == second.manager && first.definitions == second.definitions && first.count == second.count;
    }
    private static State state(MinecraftServer server) { synchronized (STATES) { return STATES.get(server); } }
    private static void replace(MinecraftServer server, State current) { synchronized (STATES) { STATES.put(server, current); } }
    private static void fail(State current, String detail) {
        current.job = null; current.index = null; current.phase = "failed"; current.detail = detail;
    }
    private static void requireThread(MinecraftServer server) {
        if (server == null || !server.isSameThread()) throw new IllegalStateException("Recipe index access requires the logical server thread");
    }
    /** Expected loading/recovery state: callers can display the reason without a per-command stack trace. */
    public static final class IndexUnavailableException extends IllegalStateException {
        private IndexUnavailableException(String reason) { super(reason); }
        @Override public synchronized Throwable fillInStackTrace() { return this; }
    }
    public record BuildStatus(String state, long generation, String phase, int totalDefinitions, int visitedDefinitions,
                              int selectedDefinitions, int normalizedDefinitions, int lookupDefinitions, long slices,
                              long activeMillis, long elapsedMillis, long maxSliceMillis, String detail) { }
    private record Source(RecipeManager manager, Collection<? extends RecipeHolder<?>> definitions, int count) { }
    private static final class State {
        final long generation;
        Source source;
        int automaticRestarts;
        int observedChanges;
        int stableSinceTick;
        int waitingSinceTick;
        String phase = "building";
        String detail = "Recipe knowledge is being scheduled";
        RecipeIndexBuilder.Job job;
        RecipeIndexBuilder.Progress lastProgress;
        RecipeIndex index;
        State(long generation) { this.generation = generation; }
    }
}
