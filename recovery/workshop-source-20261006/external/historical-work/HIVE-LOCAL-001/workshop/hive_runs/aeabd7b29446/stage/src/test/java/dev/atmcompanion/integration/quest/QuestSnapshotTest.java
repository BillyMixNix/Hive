package dev.atmcompanion.integration.quest;

import com.google.gson.Gson;
import dev.atmcompanion.state.CapabilityStatus;
import dev.atmcompanion.state.Observation;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;

class QuestSnapshotTest {
    @Test
    void availabilityUsesExplicitTeamAndFtbFlagsWithoutGuessingDependencyOperators() {
        var ready = QuestFixtures.quest("0000000000000002", true, false, true);
        var hidden = QuestFixtures.quest("0000000000000003", false, false, true);
        var completed = QuestFixtures.quest("0000000000000004", true, true, true);
        var blocked = QuestFixtures.quest("0000000000000005", true, false, false);
        var snapshot = QuestFixtures.snapshot(List.of(ready, hidden, completed, blocked), List.of(ready.id()), false);

        assertEquals(List.of(ready.id()), snapshot.availableQuestIds());
        assertFalse(ready.dependenciesSatisfied(), "Availability follows the observed canStartTasks flag, not inferred AND dependencies");
        assertEquals(CapabilityStatus.UNAVAILABLE, ready.dependencyRule().status());
        assertEquals(QuestSnapshot.TEAM_SCOPE, snapshot.progressScope());
        assertEquals(QuestSnapshot.AVAILABILITY_RULE, snapshot.availabilityRule());
    }

    @Test
    void lockedTeamCannotExposeAvailableQuests() {
        var quest = QuestFixtures.quest("0000000000000002", true, false, true);
        assertTrue(QuestFixtures.snapshot(List.of(quest), List.of(), true).availableQuestIds().isEmpty());
        assertThrows(IllegalArgumentException.class, () -> QuestFixtures.snapshot(List.of(quest), List.of(quest.id()), true));
    }

    @Test
    void hiddenContainingChapterPreventsDerivedAvailabilityEvenWhenQuestFlagIsVisible() {
        var quest = QuestFixtures.quest("0000000000000002", true, false, true);
        var chapters = List.of(new QuestSnapshot.Chapter(QuestFixtures.CHAPTER_ID, "Hidden chapter", false, false, false));
        var snapshot = new QuestSnapshot(1, "2026-09-22T12:34:56Z", OptionalQuestAccess.SUPPORTED_VERSION,
                QuestSnapshot.TEAM_SCOPE, false, chapters, List.of(quest), List.of(), QuestSnapshot.AVAILABILITY_RULE);

        assertTrue(snapshot.availableQuestIds().isEmpty());
        assertTrue(snapshot.quests().getFirst().visible(), "The original quest flag must remain an unmodified observed fact");
        assertThrows(IllegalArgumentException.class, () -> new QuestSnapshot(1, "2026-09-22T12:34:56Z",
                OptionalQuestAccess.SUPPORTED_VERSION, QuestSnapshot.TEAM_SCOPE, false, chapters,
                List.of(quest), List.of(quest.id()), QuestSnapshot.AVAILABILITY_RULE));
    }

    @Test
    void contradictingAvailabilityCannotBeSerializedAsFact() {
        var ready = QuestFixtures.quest("0000000000000002", true, false, true);
        var hidden = QuestFixtures.quest("0000000000000003", false, false, true);
        assertThrows(IllegalArgumentException.class, () -> QuestFixtures.snapshot(List.of(ready), List.of(), false));
        assertThrows(IllegalArgumentException.class, () -> QuestFixtures.snapshot(List.of(hidden), List.of(hidden.id()), false));
    }

    @Test
    void configuredItemReferenceDoesNotPretendToBeAnExactTaskRequirement() {
        var task = new QuestSnapshot.Task("0000000000000006", "ftbquests:item", "Item task", 3, 10,
                true, false, true, Observation.available(new QuestSnapshot.ItemReference("example_mod:component_item", true)),
                Observation.unavailable("Exact tag/component/count matching is not exported"));
        Gson gson = new Gson();
        assertEquals(task, gson.fromJson(gson.toJson(task), QuestSnapshot.Task.class));
        assertEquals(CapabilityStatus.UNAVAILABLE, task.requirementRule().status());
        assertNull(task.requirementRule().data());
        assertTrue(task.itemReference().data().hasComponentPatch());
    }

    @Test
    void collectionCopiesAreImmutableAndSnapshotRoundTrips() {
        var quest = QuestFixtures.quest("0000000000000002", true, false, true);
        var quests = new ArrayList<>(List.of(quest));
        var available = new ArrayList<>(List.of(quest.id()));
        var snapshot = QuestFixtures.snapshot(quests, available, false);
        quests.clear(); available.clear();
        assertEquals(1, snapshot.quests().size());
        assertEquals(1, snapshot.availableQuestIds().size());
        assertThrows(UnsupportedOperationException.class, () -> snapshot.quests().clear());
        assertThrows(UnsupportedOperationException.class, () -> snapshot.availableQuestIds().clear());
        Gson gson = new Gson();
        assertEquals(snapshot, gson.fromJson(gson.toJson(snapshot), QuestSnapshot.class));
    }

    @Test
    void identifiersTextCountsAndCollectionBoundsRejectMalformedData() {
        assertThrows(IllegalArgumentException.class, () -> QuestFixtures.quest("invalid", true, false, true));
        assertThrows(IllegalArgumentException.class, () -> new QuestSnapshot.ItemReference("not_namespaced", false));
        assertThrows(IllegalArgumentException.class, () -> new QuestSnapshot.Chapter(QuestFixtures.CHAPTER_ID,
                "x".repeat(QuestSnapshot.MAX_TEXT_LENGTH + 1), true, false, false));
        assertThrows(IllegalArgumentException.class, () -> new QuestSnapshot.Task("0000000000000006", "ftbquests:item", "Task", -1, 1,
                false, false, false, Observation.unavailable("No item"), Observation.unavailable("Not inspected")));
        var tooMany = IntStream.range(0, QuestSnapshot.MAX_QUESTS + 1).mapToObj(i -> QuestFixtures.quest(
                String.format(java.util.Locale.ROOT, "%016X", i + 2), false, false, false)).toList();
        assertThrows(IllegalArgumentException.class, () -> QuestFixtures.snapshot(tooMany, List.of(), false));
    }

    @Test
    void identifierValidationKeepsExactAsciiAndFullStringSemantics() {
        assertEquals("FEDCBA9876543210", new QuestSnapshot.Chapter("FEDCBA9876543210", "Title", true, false, false).id());
        assertEquals("example.mod-1:folder/sub_item.2", new QuestSnapshot.ItemReference("example.mod-1:folder/sub_item.2", false).item());
        for (String invalid : List.of("fedcba9876543210", "ＦEDCBA9876543210", "FEDCBA9876543210\n", " FEDCBA9876543210", "FEDCBA98765432100")) {
            assertThrows(IllegalArgumentException.class,
                    () -> new QuestSnapshot.Chapter(invalid, "Title", true, false, false), invalid);
        }
        for (String invalid : List.of("Minecraft:diamond", "minecraft:DIAMOND", "minecraft:diamond\n", "minecraft:", ":diamond", "minecraft:gem:diamond", "minecraft:dïamond")) {
            assertThrows(IllegalArgumentException.class, () -> new QuestSnapshot.ItemReference(invalid, false), invalid);
        }
    }
}
