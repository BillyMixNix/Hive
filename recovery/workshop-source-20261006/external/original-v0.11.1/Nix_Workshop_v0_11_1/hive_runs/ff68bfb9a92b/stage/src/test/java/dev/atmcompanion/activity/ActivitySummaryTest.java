package dev.atmcompanion.activity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
class ActivitySummaryTest {
 private ActivityEvent e(ActivityEvent.Type t,long q){return new ActivityEvent(1,"2026-09-23T12:34:56Z",t,List.of("minecraft:diamond"),q,ActivityEvent.Source.MANUAL);}
 @Test void countsAllTypes(){
  var s=ActivitySummary.from(List.of(
   e(ActivityEvent.Type.ITEM_GAINED,2),
   e(ActivityEvent.Type.ITEM_GAINED,7),
   e(ActivityEvent.Type.ITEM_LOST,3),
   new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_GAINED,List.of("minecraft:diamond"),null,ActivityEvent.Source.MANUAL),
   new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.DIMENSION_CHANGED,List.of("minecraft:overworld"),null,ActivityEvent.Source.MANUAL)));
  assertEquals(5,s.eventCount());
  assertEquals(12L,s.totalQuantity());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.counts().keySet());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.quantitiesByType().keySet());
  for(var t:ActivityEvent.Type.values()){
   int count=t==ActivityEvent.Type.ITEM_GAINED?3:(t==ActivityEvent.Type.ITEM_LOST||t==ActivityEvent.Type.DIMENSION_CHANGED?1:0);
   long quantity=t==ActivityEvent.Type.ITEM_GAINED?9L:(t==ActivityEvent.Type.ITEM_LOST?3L:0L);
   assertEquals(Integer.valueOf(count),s.counts().get(t),t.name());
   assertEquals(Long.valueOf(quantity),s.quantitiesByType().get(t),t.name());
  }
  assertThrows(UnsupportedOperationException.class,()->s.counts().put(ActivityEvent.Type.ITEM_GAINED,99));
  assertThrows(UnsupportedOperationException.class,()->s.quantitiesByType().put(ActivityEvent.Type.ITEM_GAINED,99L));
  assertThrows(UnsupportedOperationException.class,()->s.quantitiesByType().remove(ActivityEvent.Type.ITEM_LOST));
  assertThrows(UnsupportedOperationException.class,()->s.quantitiesByType().entrySet().iterator().next().setValue(99L));
  assertEquals(Long.valueOf(9L),s.quantitiesByType().get(ActivityEvent.Type.ITEM_GAINED));
 }
 @Test void emptyAndImmutable(){
  var s=ActivitySummary.from(List.of());
  assertEquals(0,s.eventCount());
  assertEquals(0L,s.totalQuantity());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.counts().keySet());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.quantitiesByType().keySet());
  for(var t:ActivityEvent.Type.values()){
   assertEquals(Integer.valueOf(0),s.counts().get(t),t.name());
   assertEquals(Long.valueOf(0L),s.quantitiesByType().get(t),t.name());
  }
  assertThrows(UnsupportedOperationException.class,()->s.counts().clear());
  assertThrows(UnsupportedOperationException.class,()->s.quantitiesByType().clear());
 }
 @Test void legacyConstructorPreservesValuesAndCopiesCounts(){
  java.util.Map<ActivityEvent.Type,Integer> counts=new java.util.EnumMap<>(ActivityEvent.Type.class);
  counts.put(ActivityEvent.Type.ITEM_GAINED,2);
  counts.put(ActivityEvent.Type.ITEM_LOST,1);
  var expectedCounts=java.util.Map.copyOf(counts);
  var s=new ActivitySummary(3,17L,counts);
  counts.put(ActivityEvent.Type.ITEM_GAINED,99);
  counts.clear();
  assertEquals(3,s.eventCount());
  assertEquals(17L,s.totalQuantity());
  assertEquals(expectedCounts,s.counts());
  assertEquals(java.util.EnumSet.allOf(ActivityEvent.Type.class),s.quantitiesByType().keySet());
  for(var t:ActivityEvent.Type.values())assertEquals(Long.valueOf(0L),s.quantitiesByType().get(t),t.name());
  assertThrows(UnsupportedOperationException.class,()->s.counts().clear());
  assertThrows(UnsupportedOperationException.class,()->s.quantitiesByType().put(ActivityEvent.Type.ITEM_GAINED,1L));
 }
 @Test void rejectsNull(){assertThrows(RuntimeException.class,()->ActivitySummary.from(null));assertThrows(RuntimeException.class,()->ActivitySummary.from(java.util.Arrays.asList((ActivityEvent)null)));}
}
