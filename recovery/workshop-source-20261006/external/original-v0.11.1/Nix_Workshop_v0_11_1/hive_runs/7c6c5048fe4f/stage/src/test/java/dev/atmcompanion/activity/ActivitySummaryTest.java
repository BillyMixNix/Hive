package dev.atmcompanion.activity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
class ActivitySummaryTest {
 private ActivityEvent e(ActivityEvent.Type t,long q){return new ActivityEvent(1,"2026-09-23T12:34:56Z",t,List.of("minecraft:diamond"),q,ActivityEvent.Source.MANUAL);}
 @Test void countsAllTypes(){var s=ActivitySummary.from(List.of(e(ActivityEvent.Type.ITEM_GAINED,2),e(ActivityEvent.Type.ITEM_LOST,3)));assertEquals(2,s.eventCount());assertEquals(5,s.totalQuantity());for(var t:ActivityEvent.Type.values())assertNotNull(s.counts().get(t));assertEquals(1,s.counts().get(ActivityEvent.Type.ITEM_GAINED));}
 @Test void emptyAndImmutable(){
  var s=ActivitySummary.from(List.of());
  var countsBefore=new java.util.HashMap<>(s.counts());
  for(int pass=0;pass<2;pass++){
   for(var type:ActivityEvent.Type.values())assertEquals(0,s.count(type),type.name());
   assertEquals(0,s.eventCount());
   assertEquals(0,s.totalQuantity());
   assertEquals(countsBefore,s.counts());
   assertThrows(IllegalArgumentException.class,()->s.count(null));
   assertEquals(0,s.eventCount());
   assertEquals(0,s.totalQuantity());
   assertEquals(countsBefore,s.counts());
  }
  assertThrows(UnsupportedOperationException.class,()->s.counts().clear());
 }
 @Test void rejectsNull(){assertThrows(RuntimeException.class,()->ActivitySummary.from(null));assertThrows(RuntimeException.class,()->ActivitySummary.from(java.util.Arrays.asList((ActivityEvent)null)));}
 @Test void countKeepsEveryTypeIsolated(){
  for(var present:ActivityEvent.Type.values()){
   var s=ActivitySummary.from(List.of(e(present,7)));
   for(var queried:ActivityEvent.Type.values()){
    assertEquals(present==queried?1:0,s.count(queried),"present="+present+", queried="+queried);
   }
  }
 }
 @Test void distinctCountsAndNullRejectionDoNotMutateSummary(){
  var types=ActivityEvent.Type.values();
  var events=new java.util.ArrayList<ActivityEvent>();
  for(int i=0;i<types.length;i++){
   for(int j=0;j<=i;j++)events.add(e(types[i],7));
  }
  var s=ActivitySummary.from(events);
  var countsBefore=new java.util.HashMap<>(s.counts());
  int eventCountBefore=s.eventCount();
  long quantityBefore=s.totalQuantity();
  assertEquals(events.size(),eventCountBefore);
  assertEquals(events.size()*7L,quantityBefore);
  for(int pass=0;pass<3;pass++){
   for(int i=0;i<types.length;i++){
    assertEquals(i+1,s.count(types[i]),types[i].name());
    assertEquals(countsBefore,s.counts());
    assertEquals(eventCountBefore,s.eventCount());
    assertEquals(quantityBefore,s.totalQuantity());
   }
   assertThrows(IllegalArgumentException.class,()->s.count(null));
   assertEquals(countsBefore,s.counts());
   assertEquals(eventCountBefore,s.eventCount());
   assertEquals(quantityBefore,s.totalQuantity());
  }
 }
}
