# Twin Realms Godot Prototype

This is the Contract 9 placeholder client. It renders a tiny 3D arena and talks to the Python simulation through the Contract 8 frontend boundary.

Run the backend from the repo root:

```powershell
D:\Hive\.venv\Scripts\python.exe -m twin_realms.frontend_server --scenario core --port 8765
```

Open `godot_client/project.godot` in Godot 4 and run the main scene.

Controls:

- `WASD`: move the placeholder player locally in the arena
- `1`: move to the backend Den location
- `2`: move to the backend Camp location
- `Space`: attack
- `F`: heavy attack
- `Q`: block
- `E`: dodge
- `R`: rest

The Godot client does not own truth. It requests state, submits intentions, and renders the resolved backend state/events.
