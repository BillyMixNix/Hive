package dev.atmcompanion.packtests;

import net.neoforged.fml.common.Mod;

/** Opt-in compatibility harness, never included in the production JAR or ordinary core tests. */
@Mod("atm_companion_packtests")
public final class CompanionPackTestMod {
    public CompanionPackTestMod() {
        ProductionPackProbe.registerIfEnabled();
        QuestProductionProbe.registerIfEnabled();
    }
}
