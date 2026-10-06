package dev.atmcompanion.activity;
import java.util.*;
public record ActivitySummary(int eventCount,long totalQuantity,Map<ActivityEvent.Type,Integer> counts) {
 public ActivitySummary { counts=Map.copyOf(counts); }
 public static ActivitySummary from(List<ActivityEvent> events){ Objects.requireNonNull(events); EnumMap<ActivityEvent.Type,Integer> c=new EnumMap<>(ActivityEvent.Type.class); for(var t:ActivityEvent.Type.values()) c.put(t,0); long total=0; for(var e:events){ Objects.requireNonNull(e); c.put(e.type(),c.get(e.type())+1); if(e.quantity()!=null) total+=e.quantity(); } return new ActivitySummary(events.size(),total,c); }
}
