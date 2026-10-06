package dev.atmcompanion.activity;
import java.util.*;
public record ActivitySummary(int eventCount,long totalQuantity,Map<ActivityEvent.Type,Integer> counts,Map<ActivityEvent.Type,Long> quantitiesByType) {
 public ActivitySummary {
  counts=Map.copyOf(counts);
  EnumMap<ActivityEvent.Type,Long> quantities=new EnumMap<>(ActivityEvent.Type.class);
  for(var t:ActivityEvent.Type.values()) quantities.put(t,0L);
  quantities.putAll(quantitiesByType);
  quantitiesByType=Map.copyOf(quantities);
 }
 public ActivitySummary(int eventCount,long totalQuantity,Map<ActivityEvent.Type,Integer> counts) {
  this(eventCount,totalQuantity,counts,Map.of());
 }
 public static ActivitySummary from(List<ActivityEvent> events){
  Objects.requireNonNull(events);
  EnumMap<ActivityEvent.Type,Integer> c=new EnumMap<>(ActivityEvent.Type.class);
  EnumMap<ActivityEvent.Type,Long> quantities=new EnumMap<>(ActivityEvent.Type.class);
  for(var t:ActivityEvent.Type.values()) {
   c.put(t,0);
   quantities.put(t,0L);
  }
  long total=0;
  for(var e:events){
   Objects.requireNonNull(e);
   c.put(e.type(),c.get(e.type())+1);
   if(e.quantity()!=null) {
    total+=e.quantity();
    quantities.put(e.type(),quantities.get(e.type())+e.quantity());
   }
  }
  return new ActivitySummary(events.size(),total,c,quantities);
 }
}
