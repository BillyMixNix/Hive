package dev.atmcompanion.planning;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.io.Writer;
import java.nio.charset.StandardCharsets;

/** Reusable debug output bound; never serializes live game objects. */
public final class BoundedJson {
    public static final int MAX_BYTES = 262_144;
    private static final Gson GSON = new GsonBuilder().serializeNulls().setPrettyPrinting().disableHtmlEscaping().create();
    private BoundedJson() {}
    public static String encode(Object detachedDto) {
        var writer = new Writer() {
            final StringBuilder buffer = new StringBuilder();
            @Override public void write(char[] c, int offset, int length) {
                if (length > MAX_BYTES - buffer.length()) throw new IllegalArgumentException("Debug JSON exceeds byte budget");
                buffer.append(c, offset, length);
            }
            @Override public void flush() {}
            @Override public void close() {}
            @Override public String toString() { return buffer.toString(); }
        };
        GSON.toJson(detachedDto, writer);
        String json = writer.toString();
        if (json.getBytes(StandardCharsets.UTF_8).length > MAX_BYTES) throw new IllegalArgumentException("Debug JSON exceeds UTF-8 byte budget");
        return json;
    }
}
