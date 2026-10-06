package dev.atmcompanion.integration.quest;

import com.google.gson.Gson;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class QuestOverviewTest {
    private static QuestOverview overview(boolean locked, int total, int completed, int available, List<QuestOverview.Option> options) {
        return new QuestOverview(1, "2026-09-22T12:34:56Z", OptionalQuestAccess.SUPPORTED_VERSION,
                QuestSnapshot.TEAM_SCOPE, locked, 1, total, completed, available, options,
                QuestSnapshot.AVAILABILITY_RULE, QuestOverview.OMITTED_DETAILS);
    }
    private static QuestOverview.Option option(int id) {
        return new QuestOverview.Option(String.format(java.util.Locale.ROOT, "%016X", id), "0000000000000001", "Quest " + id);
    }
    @Test
    void summaryIsImmutableRoundTripsAndExplicitlyOmitsDetailedFacts() {
        var options = new ArrayList<>(List.of(option(2), option(3)));
        var result = overview(false, 10, 3, 2, options);
        options.clear();
        assertEquals(2, result.options().size());
        assertThrows(UnsupportedOperationException.class, () -> result.options().clear());
        assertTrue(result.detail().contains("task progress, dependencies and full quest details were not collected"));
        var gson = new Gson();
        assertEquals(result, gson.fromJson(gson.toJson(result), QuestOverview.class));
        assertFalse(gson.toJson(result).contains("\"tasks\""), "Projection must not invent a known-empty task array");
    }
    @Test
    void contradictoryCountsLocksAndOptionCoverageAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> overview(false, -1, 0, 0, List.of()));
        assertThrows(IllegalArgumentException.class, () -> overview(false, 8193, 0, 0, List.of()));
        assertThrows(IllegalArgumentException.class, () -> overview(false, 10, 8, 3, List.of(option(2), option(3), option(4))));
        assertThrows(IllegalArgumentException.class, () -> overview(true, 10, 0, 1, List.of(option(2))));
        assertThrows(IllegalArgumentException.class, () -> overview(false, 10, 0, 2, List.of(option(2))));
        assertEquals(0, overview(true, 10, 3, 0, List.of()).options().size());
        assertEquals(5, overview(false, 10, 0, 10, List.of(option(2), option(3), option(4), option(5), option(6))).options().size());
    }
    @Test
    void optionsMustHaveUniqueSortedIdsAndDeclaredProjectionSemantics() {
        assertThrows(IllegalArgumentException.class, () -> overview(false, 5, 0, 2, List.of(option(2), option(2))));
        assertThrows(IllegalArgumentException.class, () -> overview(false, 5, 0, 2, List.of(option(3), option(2))));
        assertThrows(IllegalArgumentException.class, () -> new QuestOverview.Option("invalid", "0000000000000001", "Title"));
        assertThrows(IllegalArgumentException.class, () -> new QuestOverview(1, "2026-09-22T12:34:56Z", "2101.1.36",
                QuestSnapshot.TEAM_SCOPE, false, 1, 0, 0, 0, List.of(), QuestSnapshot.AVAILABILITY_RULE, "All details inspected"));
    }
}
