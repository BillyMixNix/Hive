package dev.atmcompanion.activity;
import java.util.*;
public record ActivityContext(List<ActivityEvent> events, int omittedEvents) {
 public ActivityContext { events=List.copyOf(Objects.requireNonNull(events)); if(omittedEvents<0) throw new IllegalArgumentException(); }
 public static ActivityContext from(List<ActivityEvent> source,int maxEvents,int maxBytes){ if(maxEvents<1||maxBytes<128) throw new IllegalArgumentException(); Objects.requireNonNull(source); if(source.stream().anyMatch(Objects::isNull)) throw new NullPointerException(); int start=Math.max(0,source.size()-maxEvents); return new ActivityContext(source.subList(start,source.size()),start); }
}
