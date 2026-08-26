#!/usr/bin/env bash
set -euo pipefail

ASSETS="winlator-app/app/src/main/assets"
WORK="$(pwd)/.miniverse-rootfs-work"
rm -rf "$WORK"
mkdir -p "$WORK/rootfs" "$WORK/pattern" "$WORK/game"

# Expand Winlator's own runtime and default Wine-prefix pattern.
tar --use-compress-program=unzstd -xf "$ASSETS/rootfs.tzst" -C "$WORK/rootfs"
tar --use-compress-program=unzstd -xf "$ASSETS/container_pattern.tzst" -C "$WORK/pattern"

# Expand the original developer-distributed game into a fixed C:\Miniverse folder.
unzip -q "$ASSETS/miniverse.zip" -d "$WORK/game"
GAME_EXE="$(find "$WORK/game" -type f -iname 'Miniverse.exe' | head -n 1)"
test -n "$GAME_EXE"
GAME_ROOT="$(dirname "$GAME_EXE")"

CONTAINER="$WORK/rootfs/home/xuser-1"
mkdir -p "$CONTAINER"
cp -a "$WORK/pattern/.wine" "$CONTAINER/.wine"
mkdir -p "$CONTAINER/.wine/drive_c/Miniverse"
cp -a "$GAME_ROOT/." "$CONTAINER/.wine/drive_c/Miniverse/"

# ContainerManager normally restores these shared Wine DLLs after extracting the
# compact prefix. Reproduce that at APK build time because this container ships ready-made.
python3 - <<'PY'
from pathlib import Path
import json, shutil
w=Path('.miniverse-rootfs-work')
r=w/'rootfs'
c=r/'home/xuser-1/.wine/drive_c/windows'
data=json.loads(Path('winlator-app/app/src/main/assets/common_dlls.json').read_text())
for src_name,dst_name in [('x86_64-windows','system32'),('i386-windows','syswow64')]:
    src=r/'opt/wine/lib/wine'/src_name
    dst=c/dst_name
    dst.mkdir(parents=True,exist_ok=True)
    for name in data[dst_name]:
        s=src/name
        if not s.is_file():
            raise SystemExit(f'Missing shared Wine DLL: {s}')
        shutil.copy2(s,dst/name)
PY

# Minimal fixed Winlator container metadata. Unspecified settings retain Winlator defaults.
cat > "$CONTAINER/.container" <<'JSON'
{"id":1,"name":"Miniverse Minigolf","screenSize":"800x600","dxwrapper":"wined3d","wincomponents":"direct3d=1,directsound=1,directmusic=1,directshow=0,directplay=0,xaudio=1,vcrun2005=0,vcrun2010=1,wmdecoder=1","startupSelection":1}
JSON

# The original game bytes are now part of the runtime image, so don't also ship the source ZIP.
rm -f "$ASSETS/miniverse.zip"
rm -f "$ASSETS/rootfs.tzst"

tar --zstd -cf "$ASSETS/rootfs.tzst" -C "$WORK/rootfs" .

echo "Prepared Miniverse runtime image:"
ls -lh "$ASSETS/rootfs.tzst"
sha256sum "$CONTAINER/.wine/drive_c/Miniverse/Miniverse.exe"
