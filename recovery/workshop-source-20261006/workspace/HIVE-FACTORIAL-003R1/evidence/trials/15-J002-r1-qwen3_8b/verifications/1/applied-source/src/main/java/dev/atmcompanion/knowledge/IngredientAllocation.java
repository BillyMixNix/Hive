package dev.atmcompanion.knowledge;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Exact bounded allocation for at most nine crafting ingredient positions; a stack cannot be double-counted. */
public final class IngredientAllocation {
    private IngredientAllocation() {}
    public static boolean canSatisfy(List<List<Integer>> matchingSlots, Map<Integer, Integer> counts) {
        if (matchingSlots == null || counts == null) {
            throw new IllegalArgumentException("Matching slots or counts map is null");
        }
        if (matchingSlots.size() > 9 || counts.size() > 36 || matchingSlots.stream().anyMatch(slots -> slots.size() > 36)) {
            throw new IllegalArgumentException("Crafting allocation bounds exceeded");
        }
        for (List<Integer> slots : matchingSlots) {
            if (slots == null) {
                throw new IllegalArgumentException("Matching slots list is null");
            }
            for (int slot : slots) {
                if (slot < 0 || slot >= 36) {
                    throw new IllegalArgumentException("Slot " + slot + " is out of range");
                }
            }
        }
        if (counts.values().stream().anyMatch(count -> count == null || count < 0)) {
            throw new IllegalArgumentException("Count value is null or negative");
        }
        Map<Integer, java.util.ArrayList<Integer>> assigned = new HashMap<>();
        for (int requirement = 0; requirement < matchingSlots.size(); requirement++) {
            if (!assign(requirement, matchingSlots, counts, assigned, new boolean[matchingSlots.size()])) return false;
        }
        return true;
    }
    private static boolean assign(int requirement, List<List<Integer>> matches, Map<Integer, Integer> counts,
                                  Map<Integer, java.util.ArrayList<Integer>> assigned, boolean[] visited) {
        if (visited[requirement]) return false;
        visited[requirement] = true;
        for (int slot : matches.get(requirement)) {
            var occupants = assigned.computeIfAbsent(slot, ignored -> new java.util.ArrayList<>());
            if (occupants.size() < counts.getOrDefault(slot, 0)) {
                occupants.add(requirement);
                return true;
            }
            for (int index = 0; index < occupants.size(); index++) {
                int displaced = occupants.get(index);
                if (assign(displaced, matches, counts, assigned, visited)) {
                    occupants.set(index, requirement);
                    return true;
                }
            }
        }
        return false;
    }
}
