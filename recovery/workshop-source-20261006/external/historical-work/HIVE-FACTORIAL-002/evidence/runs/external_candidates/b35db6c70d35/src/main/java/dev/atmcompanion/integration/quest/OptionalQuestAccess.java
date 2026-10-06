package dev.atmcompanion.integration.quest;

import dev.atmcompanion.state.Observation;
import dev.atmcompanion.state.Capability;
import java.util.Objects;
import java.util.Optional;
import java.util.function.Consumer;
import java.util.function.BiConsumer;
import java.util.function.Function;
import java.util.function.Supplier;

/** Pure injectable gate. The adapter factory is never invoked for absent or unsupported releases. */
public final class OptionalQuestAccess<P> {
    public static final String SUPPORTED_VERSION = "2101.1.36";
    private final Supplier<Optional<String>> installedVersion;
    private final Supplier<Function<P, Observation<QuestSnapshot>>> factory;
    private final BiConsumer<String, Throwable> diagnostics;
    private Function<P, Observation<QuestSnapshot>> adapter;

    public OptionalQuestAccess(Supplier<Optional<String>> installedVersion,
            Supplier<Function<P, Observation<QuestSnapshot>>> factory, Consumer<String> diagnostics) {
        this(installedVersion, factory, (message, failure) -> diagnostics.accept(message));
        Objects.requireNonNull(diagnostics);
    }

    public OptionalQuestAccess(Supplier<Optional<String>> installedVersion,
            Supplier<Function<P, Observation<QuestSnapshot>>> factory, BiConsumer<String, Throwable> diagnostics) {
        this.installedVersion = Objects.requireNonNull(installedVersion);
        this.factory = Objects.requireNonNull(factory);
        this.diagnostics = Objects.requireNonNull(diagnostics);
    }

    public Observation<QuestSnapshot> snapshot(P player) {
        try {
            Observation<QuestSnapshot> blocked = versionBlocker();
            if (blocked != null) return blocked;
            if (adapter == null) adapter = Objects.requireNonNull(factory.get());
            return Objects.requireNonNull(adapter.apply(player));
        } catch (RuntimeException | LinkageError | StackOverflowError error) {
            String detail = "FTB Quests observation failed (" + error.getClass().getSimpleName()
                    + "); check the server log and installed integration versions";
            diagnostics.accept(detail, error);
            return Observation.unavailable(detail);
        }
    }

    /** Readiness only. The version-specific probe is never called for an absent or unsupported optional mod. */
    public Capability capability(P player, Function<P, Capability> probe) {
        try {
            Observation<QuestSnapshot> blocked = versionBlocker();
            if (blocked != null) return Capability.from(blocked);
            return Objects.requireNonNull(probe.apply(player));
        } catch (RuntimeException | LinkageError | StackOverflowError error) {
            String detail = "FTB Quests readiness probe failed (" + error.getClass().getSimpleName() + "); see server log";
            diagnostics.accept(detail, error);
            return Capability.from(Observation.unavailable(detail));
        }
    }

    /** A separately identified projection; no full snapshot or mutable progress is cached. */
    public Observation<QuestOverview> summary(P player, Function<P, Observation<QuestOverview>> probe) {
        try {
            Observation<QuestSnapshot> blocked = versionBlocker();
            if (blocked != null) return new Observation<>(blocked.status(), null, blocked.detail());
            return Objects.requireNonNull(probe.apply(player));
        } catch (RuntimeException | LinkageError | StackOverflowError error) {
            String detail = "FTB Quests overview failed (" + error.getClass().getSimpleName() + "); see server log";
            diagnostics.accept(detail, error);
            return Observation.unavailable(detail);
        }
    }
    private Observation<QuestSnapshot> versionBlocker() {
        Optional<String> version = Objects.requireNonNull(installedVersion.get());
        if (version.isEmpty()) return Observation.notIntegrated("FTB Quests is not loaded");
        if (!SUPPORTED_VERSION.equals(version.get()))
            return Observation.unavailable("Unsupported FTB Quests API version; supported version is " + SUPPORTED_VERSION);
        return null;
    }
}
