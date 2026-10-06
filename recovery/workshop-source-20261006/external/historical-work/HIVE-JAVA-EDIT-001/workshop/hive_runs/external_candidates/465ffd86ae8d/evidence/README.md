# Verification evidence

These are **automated NeoForge GameTest fixtures**, not the user's game state and not an ATM10 world.

- `verification-final.log`: successful clean build, 37 unit tests, production mod discovery, and 8 required server tests. Local user-profile paths are redacted.
- `junit/TEST-*.xml`: original final JUnit result files.
- `live-snapshot.json`: actual production collector output for a NeoForge FakePlayer with deliberately assigned health/inventory/location; progression is unavailable because FakePlayer lacks persistent advancements.
- `real-server-player-snapshot.json`: actual collector output for the official GameTest helper's real ServerPlayer using an embedded connection, after a vanilla advancement award.
- `command-export.json`: real `/companion debug snapshot` output for the operator-permitted command fixture.

The runtime test mod appears in these snapshots because it was loaded alongside ATM Companion and NeoForge. It is excluded from the production JAR. No account credentials, server address, or real player's identity were collected. The headless test world is not distributed.
