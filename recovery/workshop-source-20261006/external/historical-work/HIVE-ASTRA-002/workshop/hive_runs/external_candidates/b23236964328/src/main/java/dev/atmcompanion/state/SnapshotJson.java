package dev.atmcompanion.state;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonParseException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.Objects;

public final class SnapshotJson {
    public static final int MAX_JSON_BYTES = 262_144;
    private static final Gson GSON = new GsonBuilder().serializeNulls().setPrettyPrinting().disableHtmlEscaping().create();
    private SnapshotJson() {}
    public static String toJson(GameSnapshot snapshot) {
        BoundedWriter writer = new BoundedWriter();
        GSON.toJson(Objects.requireNonNull(snapshot), writer);
        String json = writer.toString();
        checkSize(json);
        return json;
    }
    public static GameSnapshot fromJson(String json) {
        checkSize(json);
        try {
            GameSnapshot snapshot = GSON.fromJson(json, GameSnapshot.class);
            if (snapshot == null) throw new IllegalArgumentException("Snapshot must be a JSON object");
            return snapshot;
        } catch (JsonParseException exception) {
            throw new IllegalArgumentException("Invalid snapshot JSON", exception);
        }
    }
    private static void checkSize(String json) {
        Objects.requireNonNull(json);
        if (json.length() > MAX_JSON_BYTES) throw new IllegalArgumentException("Snapshot exceeds maximum character bound");
        if (json.getBytes(StandardCharsets.UTF_8).length > MAX_JSON_BYTES) throw new IllegalArgumentException("Snapshot exceeds " + MAX_JSON_BYTES + " UTF-8 bytes");
    }
    /** Bound allocation while Gson writes, before the final exact UTF-8 size check. */
    private static final class BoundedWriter extends Writer {
        private final StringBuilder output = new StringBuilder();
        private void reserve(int additional) {
            if (additional < 0 || additional > MAX_JSON_BYTES - output.length()) {
                throw new IllegalArgumentException("Snapshot exceeds maximum character bound");
            }
        }
        @Override public void write(char[] characters, int offset, int length) {
            reserve(length);
            output.append(characters, offset, length);
        }
        @Override public void write(String characters, int offset, int length) {
            reserve(length);
            output.append(characters, offset, offset + length);
        }
        @Override public void write(int character) {
            reserve(1);
            output.append((char) character);
        }
        @Override public void flush() {}
        @Override public void close() {}
        @Override public String toString() { return output.toString(); }
    }
}
