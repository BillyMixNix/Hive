package dev.atmcompanion.integration;

import dev.atmcompanion.state.Capability;
import java.util.Map;

/** An adapter must not retain live world objects or inspect Minecraft from worker threads. */
public interface Integration {
    boolean isAvailable();
    Map<String, Capability> capabilities();
}
