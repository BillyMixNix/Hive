package dev.atmcompanion.activity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
class ActivitySummaryTest {
 private ActivityEvent e(ActivityEvent.Type t,long q){return new ActivityEvent(1,"2026-09-23T12:34:56Z",t,List.of("minecraft:diamond"),q,ActivityEvent.Source.MANUAL);}
 @Test void countsAllTypes(){var s=ActivitySummary.from(List.of(e(ActivityEvent.Type.ITEM_GAINED,2),e(ActivityEvent.Type.ITEM_LOST,3)));assertEquals(2,s.eventCount());assertEquals(5,s.totalQuantity());for(var t:ActivityEvent.Type.values())assertNotNull(s.counts().get(t));assertEquals(1,s.counts().get(ActivityEvent.Type.ITEM_GAINED));}
 @Test void emptyAndImmutable(){var s=ActivitySummary.from(List.of());assertEquals(0,s.totalQuantity());assertThrows(UnsupportedOperationException.class,()->s.counts().clear());}
 @Test void rejectsNull(){assertThrows(RuntimeException.class,()->ActivitySummary.from(null));assertThrows(RuntimeException.class,()->ActivitySummary.from(java.util.Arrays.asList((ActivityEvent)null)));}
}
