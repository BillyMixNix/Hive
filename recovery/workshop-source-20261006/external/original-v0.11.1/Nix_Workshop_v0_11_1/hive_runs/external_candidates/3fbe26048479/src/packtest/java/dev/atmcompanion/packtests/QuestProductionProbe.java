package dev.atmcompanion.packtests;

import com.mojang.authlib.GameProfile;
import com.mojang.logging.LogUtils;
import dev.atmcompanion.integration.quest.QuestService;
import dev.atmcompanion.planning.BoundedJson;
import dev.ftb.mods.ftbquests.api.FTBQuestsAPI;
import dev.ftb.mods.ftbteams.api.FTBTeamsAPI;
import io.netty.channel.embedded.EmbeddedChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import net.minecraft.network.Connection;
import net.minecraft.network.protocol.PacketFlow;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.CommonListenerCookie;
import net.neoforged.fml.ModList;
import net.neoforged.fml.loading.FMLLoader;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import net.neoforged.neoforge.network.registration.NetworkRegistry;

/** Aggregate-only quest performance probe, gated to the marked disposable official server pack. */
public final class QuestProductionProbe {
    private static final String PROPERTY = "atm_companion.questSmoke";
    private final Path directory;
    private final QuestService service = new QuestService();
    private final ArrayList<Map<String, Object>> samples = new ArrayList<>();
    private ServerPlayer player;
    private int ticks, nextSample;
    private boolean finished;

    private QuestProductionProbe(Path directory) { this.directory = directory; }
    public static void registerIfEnabled() {
        Path directory = Path.of("").toAbsolutePath().normalize();
        if (FMLLoader.isProduction() && Boolean.getBoolean(PROPERTY)
                && Files.isRegularFile(directory.resolve(ProductionPackProbe.MARKER), LinkOption.NOFOLLOW_LINKS))
            NeoForge.EVENT_BUS.addListener(new QuestProductionProbe(directory)::tick);
    }
    private boolean authorized(MinecraftServer server) {
        return Boolean.getBoolean(PROPERTY) && server.isDedicatedServer()
                && server.getServerDirectory().toAbsolutePath().normalize().equals(directory)
                && Files.isRegularFile(directory.resolve(ProductionPackProbe.MARKER), LinkOption.NOFOLLOW_LINKS);
    }
    private void tick(ServerTickEvent.Post event) {
        var server = event.getServer();
        if (finished || !authorized(server)) return;
        ticks++;
        try {
            if (ticks > 1200) throw new IllegalStateException("Quest probe did not finish within 1200 server ticks");
            if (player == null) {
                var file = FTBQuestsAPI.api().getQuestFile(false);
                if (file == null || file.isLoading() || !FTBTeamsAPI.api().isManagerLoaded()) return;
                var profile = new GameProfile(UUID.nameUUIDFromBytes("atm-disposable-quest-probe".getBytes(StandardCharsets.UTF_8)), "quest_probe");
                var cookie = CommonListenerCookie.createInitial(profile, false);
                player = new ServerPlayer(server, server.overworld(), profile, cookie.clientInformation());
                var connection = new Connection(PacketFlow.SERVERBOUND);
                new EmbeddedChannel(connection);
                NetworkRegistry.configureMockConnection(connection);
                server.getPlayerList().placeNewPlayer(connection, player, cookie);
                // Test-only fixture preparation: never called by the observer or in a user world.
                var team = FTBTeamsAPI.api().getManager().getTeamForPlayer(player).orElseThrow();
                file.getOrCreateTeamData(team);
                nextSample = ticks + 20;
                return;
            }
            if (ticks < nextSample) return;
            if (samples.size() < 4) {
                long started = System.nanoTime();
                var summary = service.summary(player);
                var result = new LinkedHashMap<String, Object>();
                result.put("sample", samples.size() + 1);
                result.put("mode", "summary");
                result.put("elapsedNanos", System.nanoTime() - started);
                result.put("status", summary.status().name());
                result.put("detail", summary.detail());
                if (summary.data() != null) {
                    var data = summary.data();
                    result.put("chapters", data.chapterCount());
                    result.put("quests", data.questCount());
                    result.put("completed", data.completedQuests());
                    result.put("available", data.availableQuests());
                    result.put("options", data.options().size());
                }
                samples.add(result);
                nextSample = ticks + 20;
                return;
            }
            long began = System.nanoTime();
            var observed = service.snapshot(player);
            long nanos = System.nanoTime() - began;
            var sample = new LinkedHashMap<String, Object>();
            sample.put("sample", samples.size() + 1);
            sample.put("mode", "full");
            sample.put("elapsedNanos", nanos);
            sample.put("status", observed.status().name());
            sample.put("detail", observed.detail());
            if (observed.data() != null) {
                var data = observed.data();
                sample.put("chapters", data.chapters().size());
                sample.put("quests", data.quests().size());
                sample.put("tasks", data.quests().stream().mapToInt(q -> q.tasks().size()).sum());
                sample.put("dependencies", data.quests().stream().mapToInt(q -> q.dependencies().size()).sum());
                sample.put("available", data.availableQuestIds().size());
            }
            samples.add(sample);
            LogUtils.getLogger().info("ATM Companion disposable full-pack quest sample {}: {} in {} ms", samples.size(), observed.status(), nanos / 1_000_000);
            nextSample = ticks + 20;
            if (samples.size() == 8) finish(server, null);
        } catch (RuntimeException | LinkageError | StackOverflowError failure) { finish(server, failure); }
    }
    private void finish(MinecraftServer server, Throwable failure) {
        if (!authorized(server)) return;
        finished = true;
        var result = new LinkedHashMap<String, Object>();
        result.put("schemaVersion", 1);
        result.put("timestamp", Instant.now().toString());
        result.put("scope", "Disposable official ATM10 server-pack quest observation with synthetic logged-in team; aggregate evidence only");
        result.put("companionVersion", ModList.get().getModContainerById("atm_companion").orElseThrow().getModInfo().getVersion().toString());
        result.put("loadedModCount", ModList.get().getMods().size());
        result.put("samples", samples);
        result.put("terminalStatus", failure == null ? "measured" : "failed");
        if (failure != null) {
            result.put("errorType", failure.getClass().getName());
            result.put("error", String.valueOf(failure.getMessage()).substring(0, Math.min(500, String.valueOf(failure.getMessage()).length())));
        }
        try {
            Files.createDirectories(directory.resolve("evidence"));
            Files.writeString(directory.resolve("evidence/m32-quest-production-probe.json"), BoundedJson.encode(result), StandardCharsets.UTF_8);
            if (failure != null) LogUtils.getLogger().error("ATM Companion quest probe failed", failure);
        } catch (Exception writeFailure) { LogUtils.getLogger().error("ATM Companion quest probe evidence write failed", writeFailure); }
        finally { if (authorized(server)) server.halt(false); }
    }
}
