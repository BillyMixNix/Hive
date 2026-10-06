package dev.atmcompanion.integration.quest;

import dev.atmcompanion.state.CapabilityStatus;
import dev.atmcompanion.state.Capability;
import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class OptionalQuestAccessTest {
    @Test
    void absentModNeverLoadsAdapterAndNeverClaimsKnownEmptyQuests() {
        var gate = new OptionalQuestAccess<String>(Optional::empty, () -> {
            fail("Absent integration factory was called");
            return player -> Observation.available(QuestFixtures.empty());
        }, message -> fail(message));
        var result = gate.snapshot("fixture-player");
        assertEquals(CapabilityStatus.NOT_INTEGRATED, result.status());
        assertNull(result.data());
    }

    @Test
    void unsupportedVersionNeverLoadsVersionSpecificClasses() {
        var gate = new OptionalQuestAccess<String>(() -> Optional.of("future-incompatible-version"), () -> {
            fail("Unsupported integration factory was called");
            return player -> Observation.available(QuestFixtures.empty());
        }, message -> fail(message));
        var result = gate.snapshot("fixture-player");
        assertEquals(CapabilityStatus.UNAVAILABLE, result.status());
        assertNull(result.data());
        assertTrue(result.detail().contains("Unsupported FTB Quests API version"));
    }

    @Test
    void supportedAdapterIsCachedAndReceivesEachInvokingPlayer() {
        var created = new AtomicInteger();
        var observed = new ArrayList<String>();
        var gate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION), () -> {
            created.incrementAndGet();
            return player -> { observed.add(player); return Observation.available(QuestFixtures.empty()); };
        }, message -> fail(message));
        assertEquals(CapabilityStatus.AVAILABLE, gate.snapshot("first-player").status());
        assertEquals(CapabilityStatus.AVAILABLE, gate.snapshot("second-player").status());
        assertEquals(1, created.get());
        assertEquals(java.util.List.of("first-player", "second-player"), observed);
    }

    @Test
    void runtimeLinkageAndQuestGraphStackOverflowFailuresDegradeToUnknown() {
        for (Throwable failure : new Throwable[]{new IllegalStateException("Unsupported API"),
                new NoClassDefFoundError("MissingOptionalClass"), new StackOverflowError("Cyclic quest graph")}) {
            var messages = new ArrayList<String>();
            var causes = new ArrayList<Throwable>();
            var gate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                    () -> player -> {
                        if (failure instanceof RuntimeException runtime) throw runtime;
                        throw (Error) failure;
                    }, (message, cause) -> { messages.add(message); causes.add(cause); });
            var result = gate.snapshot("fixture-player");
            assertEquals(CapabilityStatus.UNAVAILABLE, result.status());
            assertNull(result.data());
            assertEquals(java.util.List.of(failure), causes);
            assertEquals(1, messages.size());
            assertTrue(messages.getFirst().contains(failure.getClass().getSimpleName()));
        }
    }

    @Test
    void nullAdapterResponseAndFactoryFailureCannotBecomeAvailable() {
        var messages = new ArrayList<String>();
        var nullGate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                () -> player -> null, message -> messages.add(message));
        assertEquals(CapabilityStatus.UNAVAILABLE, nullGate.snapshot("fixture-player").status());
        var brokenFactory = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                () -> { throw new ExceptionInInitializerError("Initialization failed"); }, message -> messages.add(message));
        assertEquals(CapabilityStatus.UNAVAILABLE, brokenFactory.snapshot("fixture-player").status());
        assertEquals(2, messages.size());
    }

    @Test
    void knownEmptyQuestFileRemainsDistinctFromUnavailable() {
        var gate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                () -> player -> Observation.available(QuestFixtures.empty()), message -> fail(message));
        var result = gate.snapshot("fixture-player");
        assertEquals(CapabilityStatus.AVAILABLE, result.status());
        assertNotNull(result.data());
        assertTrue(result.data().quests().isEmpty());
        assertTrue(result.data().availableQuestIds().isEmpty());
    }

    @Test
    void readinessForAbsentOrUnsupportedVersionDoesNotLinkOptionalCode() {
        for (var version : java.util.List.of(Optional.<String>empty(), Optional.of("unsupported"))) {
            var gate = new OptionalQuestAccess<String>(() -> version,
                    () -> { throw new AssertionError("Readiness initialized the snapshot factory"); }, message -> fail(message));
            var result = gate.capability("fixture-player", player -> {
                throw new AssertionError("Absent/unsupported version entered optional readiness code");
            });
            assertEquals(version.isEmpty() ? CapabilityStatus.NOT_INTEGRATED : CapabilityStatus.UNAVAILABLE, result.status());
        }
    }

    @Test
    void readinessNeverCollectsSnapshotAndRechecksEveryPlayer() {
        var called = new ArrayList<String>();
        var gate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                () -> { throw new AssertionError("Readiness initialized the snapshot factory"); }, message -> fail(message));
        java.util.function.Function<String, Capability> probe = player -> {
            called.add(player);
            return new Capability(player.equals("mapped") ? CapabilityStatus.AVAILABLE : CapabilityStatus.UNAVAILABLE,
                    "Readiness only; quest book and progress details not collected");
        };
        assertEquals(CapabilityStatus.AVAILABLE, gate.capability("mapped", probe).status());
        assertEquals(CapabilityStatus.UNAVAILABLE, gate.capability("unmapped", probe).status());
        assertEquals(java.util.List.of("mapped", "unmapped"), called);
    }

    @Test
    void readinessErrorsAndNullResultsCannotBecomeAvailable() {
        var diagnostics = new ArrayList<Throwable>();
        var gate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                () -> { throw new AssertionError("Readiness initialized the snapshot factory"); },
                (message, failure) -> diagnostics.add(failure));
        for (Throwable failure : new Throwable[]{new IllegalStateException("Unavailable team"),
                new NoClassDefFoundError("Optional API"), new StackOverflowError("Invalid graph")}) {
            var result = gate.capability("fixture", player -> {
                if (failure instanceof RuntimeException runtime) throw runtime;
                throw (Error) failure;
            });
            assertEquals(CapabilityStatus.UNAVAILABLE, result.status());
            assertSame(failure, diagnostics.getLast());
        }
        assertEquals(CapabilityStatus.UNAVAILABLE, gate.capability("fixture", player -> null).status());
        assertEquals(4, diagnostics.size());
    }

    @Test
    void summaryGateDoesNotLoadFullSnapshotFactoryOrUnsupportedApi() {
        for (var version : java.util.List.of(Optional.<String>empty(), Optional.of("unsupported"), Optional.of(OptionalQuestAccess.SUPPORTED_VERSION))) {
            var calls = new AtomicInteger();
            var gate = new OptionalQuestAccess<String>(() -> version,
                    () -> { throw new AssertionError("Summary initialized full snapshot factory"); }, message -> fail(message));
            var observation = gate.summary("fixture", player -> {
                calls.incrementAndGet();
                return Observation.available(new QuestOverview(1, "2026-09-22T12:34:56Z", OptionalQuestAccess.SUPPORTED_VERSION,
                        QuestSnapshot.TEAM_SCOPE, false, 0, 0, 0, 0, java.util.List.of(),
                        QuestSnapshot.AVAILABILITY_RULE, QuestOverview.OMITTED_DETAILS));
            });
            boolean supported = version.filter(OptionalQuestAccess.SUPPORTED_VERSION::equals).isPresent();
            assertEquals(supported ? 1 : 0, calls.get());
            assertEquals(supported ? CapabilityStatus.AVAILABLE : version.isEmpty() ? CapabilityStatus.NOT_INTEGRATED : CapabilityStatus.UNAVAILABLE,
                    observation.status());
            if (!supported) assertNull(observation.data());
        }
    }

    @Test
    void failedOrNullSummaryNeverBecomesKnownEmptyData() {
        var errors = new ArrayList<Throwable>();
        var gate = new OptionalQuestAccess<String>(() -> Optional.of(OptionalQuestAccess.SUPPORTED_VERSION),
                () -> { throw new AssertionError("Summary initialized full snapshot factory"); }, (message, error) -> errors.add(error));
        for (Throwable failure : new Throwable[]{new IllegalArgumentException("Malformed definition"), new NoClassDefFoundError("Missing API"), new StackOverflowError("Cycle")}) {
            var observation = gate.summary("fixture", player -> {
                if (failure instanceof RuntimeException runtime) throw runtime;
                throw (Error) failure;
            });
            assertEquals(CapabilityStatus.UNAVAILABLE, observation.status());
            assertNull(observation.data());
            assertSame(failure, errors.getLast());
        }
        assertNull(gate.summary("fixture", player -> null).data());
        assertEquals(4, errors.size());
    }
}
