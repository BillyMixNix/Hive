package dev.atmcompanion;

import com.mojang.logging.LogUtils;
import dev.atmcompanion.command.CompanionCommands;
import dev.atmcompanion.knowledge.RuntimeKnowledge;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import org.slf4j.Logger;

@Mod(ATMCompanion.MOD_ID)
public final class ATMCompanion {
    public static final String MOD_ID = "atm_companion";
    private static final Logger LOGGER = LogUtils.getLogger();
    public ATMCompanion() {
        NeoForge.EVENT_BUS.addListener(this::registerCommands);
        RuntimeKnowledge.install();
        LOGGER.info("ATM Companion M3 initialized: staged recipe knowledge, material planning, nearby vanilla stations and one-operation observations; no AI/network client");
    }
    private void registerCommands(RegisterCommandsEvent event) {
        CompanionCommands.register(event.getDispatcher());
    }
}

// NFRT source-sensitivity probe: no behavior change.
