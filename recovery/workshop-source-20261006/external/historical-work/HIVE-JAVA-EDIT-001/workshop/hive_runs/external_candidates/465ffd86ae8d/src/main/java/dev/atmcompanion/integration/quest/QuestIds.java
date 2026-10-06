package dev.atmcompanion.integration.quest;

import java.util.HexFormat;

/** Exact FTB 2101.1.36 %016X identity representation, without a Formatter allocation per object. */
final class QuestIds {
    private static final HexFormat HEX = HexFormat.of().withUpperCase();
    private QuestIds() { }
    static String format(long id) { return HEX.toHexDigits(id); }
}
