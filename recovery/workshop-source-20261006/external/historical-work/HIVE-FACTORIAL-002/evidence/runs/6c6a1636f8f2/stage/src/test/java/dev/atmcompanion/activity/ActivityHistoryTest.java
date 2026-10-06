package dev.atmcompanion.activity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
class ActivityHistoryTest {
 private ActivityEvent e(String id){return new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_GAINED,List.of(id),1L,ActivityEvent.Source.MANUAL);}
 @Test void boundedAndOrdered(){var h=new ActivityHistory(2);h.append(e("minecraft:a"));h.append(e("minecraft:b"));h.append(e("minecraft:c"));assertEquals(List.of(e("minecraft:b"),e("minecraft:c")),h.recent());assertEquals(2,h.size());}
 @Test void immutableAndClear(){var h=new ActivityHistory(1);h.append(e("minecraft:a"));assertThrows(UnsupportedOperationException.class,()->h.recent().clear());h.clear();assertEquals(0,h.size());}
 @Test void rejectsInvalid(){assertThrows(RuntimeException.class,()->new ActivityHistory(0));assertThrows(RuntimeException.class,()->new ActivityHistory(257));assertThrows(RuntimeException.class,()->new ActivityHistory(1).append(null));}
}
