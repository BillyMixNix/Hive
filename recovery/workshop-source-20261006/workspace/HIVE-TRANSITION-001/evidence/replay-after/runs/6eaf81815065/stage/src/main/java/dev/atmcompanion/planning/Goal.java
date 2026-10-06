package dev.atmcompanion.planning;

/** Persistent target is a registry identity and quantity, never a cached plan or inventory. */
public record Goal(String item, int quantity) {
    public Goal {
        if (item == null || item.length() > 256 || !item.matches("[a-z0-9_.-]+:[a-z0-9/._-]+"))
            throw new IllegalArgumentException("Invalid goal item ID");
        if (quantity < 1 || quantity > 4096) throw new IllegalArgumentException("Goal quantity must be 1..4096");
    }
}
