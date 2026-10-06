# Third-party components

This project uses the Gradle wrapper from the official NeoForge 1.21.1 ModDevGradle MDK, commit `4e1be6e906e1b32a753e3580af4ea1bcc3dbc79e`:
https://github.com/NeoForgeMDKs/MDK-1.21.1-ModDevGradle

Gradle wrapper scripts and JAR are Apache License 2.0 software. The license is included at `gradle/wrapper/LICENSE.txt`; see also https://www.apache.org/licenses/LICENSE-2.0 and https://github.com/gradle/gradle . The wrapper scripts retain their original license headers.

Minecraft, NeoForge, Gson, JUnit, and modpack binaries are not bundled in the source distribution. Development dependencies are resolved by Gradle. Mojang mappings have their own terms: https://github.com/NeoForged/NeoForm/blob/main/Mojang.md . ATM Companion is not an official Minecraft, Mojang, Microsoft, NeoForge, or All the Mods product.

FTB Quests, FTB Library, FTB Teams and Architectury are optional compile/test dependencies downloaded from their publishers' Maven repositories. Their binaries and source are not bundled. Their publisher licenses apply; see https://github.com/FTBTeam and https://github.com/architectury/architectury-api .
