package dev.atmcompanion.integration.quest;

import com.mojang.logging.LogUtils;
import dev.atmcompanion.state.Capability;
import dev.atmcompanion.state.Observation;
import dev.atmcompanion.state.SnapshotService;
import net.minecraft.server.level.ServerPlayer;
import net.neoforged.fml.ModList;

/** No optional types appear in public/core signatures; FTB linkage is behind the version gate. */
public final class QuestService {
    private final OptionalQuestAccess<ServerPlayer> access = new OptionalQuestAccess<>(
            () -> ModList.get().getModContainerById("ftbquests").map(m -> m.getModInfo().getVersion().toString()),
            () -> new FtbQuestsAdapter()::snapshot,
            (message, failure) -> LogUtils.getLogger().warn(message, failure));

    public Observation<QuestSnapshot> snapshot(ServerPlayer player) {
        SnapshotService.requireServerThread(player);
        return access.snapshot(player);
    }

    public Capability capability(ServerPlayer player) {
        SnapshotService.requireServerThread(player);
        return access.capability(player, invokingPlayer -> FtbQuestsAdapter.capability(invokingPlayer));
    }

    public Observation<QuestOverview> summary(ServerPlayer player) {
        SnapshotService.requireServerThread(player);
        return access.summary(player, invokingPlayer -> FtbQuestsAdapter.summary(invokingPlayer));
    }
}
