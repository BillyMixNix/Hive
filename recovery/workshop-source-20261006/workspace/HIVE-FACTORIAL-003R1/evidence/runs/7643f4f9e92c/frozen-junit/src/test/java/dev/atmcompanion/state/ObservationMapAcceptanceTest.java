package dev.atmcompanion.state;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class ObservationMapAcceptanceTest {
    @Test void availableValueMapsExactlyOnceWithoutLosingDetail() {
        var calls = new AtomicInteger();
        var original = new Observation<>(CapabilityStatus.AVAILABLE, 3, "from fixture");
        var mapped = original.map(value -> { calls.incrementAndGet(); return "v" + value; });
        assertEquals(1, calls.get());
        assertEquals(CapabilityStatus.AVAILABLE, mapped.status());
        assertEquals("v3", mapped.data());
        assertEquals("from fixture", mapped.detail());
        assertEquals(3, original.data());
    }

    @Test void unknownStatesDoNotInvokeMapperOrGainData() {
        var unavailable = Observation.<Integer>unavailable("not scanned");
        var notIntegrated = Observation.<Integer>notIntegrated("mod absent");
        var a = unavailable.map(value -> { throw new AssertionError("must not map"); });
        var b = notIntegrated.map(value -> { throw new AssertionError("must not map"); });
        assertEquals(CapabilityStatus.UNAVAILABLE, a.status());
        assertEquals("not scanned", a.detail());
        assertNull(a.data());
        assertEquals(CapabilityStatus.NOT_INTEGRATED, b.status());
        assertEquals("mod absent", b.detail());
        assertNull(b.data());
    }

    @Test void nullMapperOrMappedValueIsRejected() {
        assertThrows(RuntimeException.class, () -> Observation.available(1).map(null));
        assertThrows(RuntimeException.class, () -> Observation.available(1).map(value -> null));
    }
}
