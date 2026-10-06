package dev.atmcompanion.activity;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
class ActivityContextTest {
 private ActivityEvent e(String id){return new ActivityEvent(1,"2026-09-23T12:34:56Z",ActivityEvent.Type.ITEM_GAINED,List.of(id),1L,ActivityEvent.Source.MANUAL);}
 @Test void keepsNewestAndReturnsChronological(){var c=ActivityContext.from(List.of(e("minecraft:a"),e("minecraft:b"),e("minecraft:c")),2,4096);assertEquals(List.of(e("minecraft:b"),e("minecraft:c")),c.events());assertEquals(1,c.omittedEvents());}
 @Test void immutableAndBounds(){var c=ActivityContext.from(List.of(e("minecraft:a")),1,4096);assertThrows(UnsupportedOperationException.class,()->c.events().clear());assertThrows(RuntimeException.class,()->ActivityContext.from(List.of(),0,4096));assertThrows(RuntimeException.class,()->ActivityContext.from(List.of(),1,127));}
 @Test void rejectsNull(){assertThrows(RuntimeException.class,()->ActivityContext.from(null,1,4096));}
}
