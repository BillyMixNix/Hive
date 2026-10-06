package dev.atmcompanion.activity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
class ActivityHistoryTest {
 private ActivityEvent e(String id){return new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_GAINED,List.of(id),1L,ActivityEvent.Source.MANUAL);}
 @Test void boundedAndOrdered(){var h=new ActivityHistory(2);h.append(e("minecraft:a"));h.append(e("minecraft:b"));h.append(e("minecraft:c"));assertEquals(List.of(e("minecraft:b"),e("minecraft:c")),h.recent());assertEquals(2,h.size());}
 @Test void immutableAndClear(){var h=new ActivityHistory(1);h.append(e("minecraft:a"));assertThrows(UnsupportedOperationException.class,()->h.recent().clear());h.clear();assertEquals(0,h.size());}
 @Test void emptySummaryRemainsEmptyAfterAppend(){
  var h=new ActivityHistory(2);
  var empty=h.summary();
  assertSummary(empty,0,0L,0,0L,0,0L);
  assertThrows(UnsupportedOperationException.class,()->empty.quantitiesByType().put(ActivityEvent.Type.ITEM_GAINED,1L));
  h.append(e("minecraft:a"));
  assertSummary(h.summary(),1,1L,1,1L,0,0L);
  assertSummary(empty,0,0L,0,0L,0,0L);
 }
 @Test void summarizesRetainedEventsAndPreservesSnapshotsAfterAppendAndEviction(){
  var h=new ActivityHistory(2);
  h.append(new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_GAINED,List.of("minecraft:a"),5L,ActivityEvent.Source.MANUAL));
  var first=h.summary();
  assertSummary(first,1,5L,1,5L,0,0L);

  h.append(new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_LOST,List.of("minecraft:b"),3L,ActivityEvent.Source.MANUAL));
  var full=h.summary();
  assertSummary(full,2,8L,1,5L,1,3L);
  assertSummary(first,1,5L,1,5L,0,0L);

  h.append(new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_GAINED,List.of("minecraft:c"),7L,ActivityEvent.Source.MANUAL));
  var retained=h.summary();
  assertSummary(retained,2,10L,1,7L,1,3L);
  assertSummary(first,1,5L,1,5L,0,0L);
  assertSummary(full,2,8L,1,5L,1,3L);
  assertThrows(UnsupportedOperationException.class,()->retained.quantitiesByType().clear());
  assertThrows(UnsupportedOperationException.class,()->retained.counts().clear());

  h.append(new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_LOST,List.of("minecraft:d"),null,ActivityEvent.Source.MANUAL));
  assertSummary(h.summary(),2,7L,1,7L,1,0L);
  assertSummary(retained,2,10L,1,7L,1,3L);
  assertSummary(full,2,8L,1,5L,1,3L);
  assertSummary(first,1,5L,1,5L,0,0L);
 }
 private void assertSummary(ActivitySummary s,int eventCount,long totalQuantity,int gainedCount,long gainedQuantity,int lostCount,long lostQuantity){
  assertEquals(eventCount,s.eventCount());
  assertEquals(totalQuantity,s.totalQuantity());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.counts().keySet());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.quantitiesByType().keySet());
  for(var t:ActivityEvent.Type.values()){
   int count=t==ActivityEvent.Type.ITEM_GAINED?gainedCount:(t==ActivityEvent.Type.ITEM_LOST?lostCount:0);
   long quantity=t==ActivityEvent.Type.ITEM_GAINED?gainedQuantity:(t==ActivityEvent.Type.ITEM_LOST?lostQuantity:0L);
   assertEquals(Integer.valueOf(count),s.counts().get(t),t.name());
   assertEquals(Long.valueOf(quantity),s.quantitiesByType().get(t),t.name());
  }
 }
 @Test void rejectsInvalid(){assertThrows(RuntimeException.class,()->new ActivityHistory(0));assertThrows(RuntimeException.class,()->new ActivityHistory(257));assertThrows(RuntimeException.class,()->new ActivityHistory(1).append(null));}
}
