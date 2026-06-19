extends Node3D

const BACKEND_URL := "http://127.0.0.1:8765"

var world_state := {}
var player_mesh: MeshInstance3D
var enemy_mesh: MeshInstance3D
var floor_mesh: MeshInstance3D
var local_velocity := Vector3.ZERO

@onready var camera: Camera3D = $Camera3D
@onready var state_request: HTTPRequest = $StateRequest
@onready var command_request: HTTPRequest = $CommandRequest
@onready var status_label: Label = $HUD/Panel/Status
@onready var log_label: Label = $HUD/Panel/Log


func _ready() -> void:
	_build_arena()
	state_request.request_completed.connect(_on_state_response)
	command_request.request_completed.connect(_on_command_response)
	_request_state()


func _physics_process(delta: float) -> void:
	if player_mesh == null:
		return
	var input := Vector3.ZERO
	input.x = Input.get_axis("ui_left", "ui_right")
	input.z = Input.get_axis("ui_up", "ui_down")
	if input.length() > 0.0:
		input = input.normalized()
	local_velocity = input * 5.0
	player_mesh.position += local_velocity * delta
	camera.position = player_mesh.position + Vector3(0, 12, 16)
	camera.look_at(player_mesh.position, Vector3.UP)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("attack"):
		_submit_first_command("attack")
	elif event.is_action_pressed("heavy_attack"):
		_submit_first_command("heavy_attack")
	elif event.is_action_pressed("block"):
		_submit_first_command("block")
	elif event.is_action_pressed("dodge"):
		_submit_first_command("dodge")
	elif event.is_action_pressed("rest"):
		_submit_first_command("rest")
	elif event.is_action_pressed("move_den"):
		_submit_move("loc:den")
	elif event.is_action_pressed("move_camp"):
		_submit_move("loc:camp")


func _request_state() -> void:
	var error := state_request.request(BACKEND_URL + "/state")
	if error != OK:
		status_label.text = "Backend unavailable: " + str(error)


func _submit_first_command(command_name: String) -> void:
	for command in world_state.get("available_player_commands", []):
		if command.get("command", "") == command_name:
			_submit_command(command)
			return
	log_label.text = "No backend affordance for " + command_name


func _submit_move(destination_id: String) -> void:
	for command in world_state.get("available_player_commands", []):
		if command.get("command", "") == "move" and command.get("intent", {}).get("destination_id", "") == destination_id:
			_submit_command(command)
			return
	log_label.text = "No backend route to " + destination_id


func _submit_command(command: Dictionary) -> void:
	var body := JSON.stringify(command)
	var headers := PackedStringArray(["Content-Type: application/json"])
	var error := command_request.request(BACKEND_URL + "/command", headers, HTTPClient.METHOD_POST, body)
	if error != OK:
		log_label.text = "Command request failed: " + str(error)


func _on_state_response(_result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if response_code != 200:
		status_label.text = "Backend state error: " + str(response_code)
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		status_label.text = "Backend returned invalid state"
		return
	world_state = parsed
	_render_world()


func _on_command_response(_result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	if response_code != 200:
		log_label.text = "Backend command error: " + str(response_code)
		return
	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if typeof(parsed) != TYPE_DICTIONARY:
		log_label.text = "Backend returned invalid turn"
		return
	world_state = parsed.get("world_state", {})
	_render_world()
	_render_events(parsed.get("events", []))
	_play_event_hooks(parsed.get("events", []))


func _render_world() -> void:
	var entities: Dictionary = world_state.get("entities", {})
	if entities.has("char:player"):
		var player := entities["char:player"]
		_sync_mesh(player_mesh, player.get("position", {}))
	if entities.has("char:hostile"):
		var hostile := entities["char:hostile"]
		enemy_mesh.visible = hostile.get("alive", false)
		_sync_mesh(enemy_mesh, hostile.get("position", {}))
	var player_state: Dictionary = entities.get("char:player", {})
	var enemy_state: Dictionary = entities.get("char:hostile", {})
	status_label.text = "Player HP %s/%s STA %s/%s | Enemy HP %s/%s | Turn %s" % [
		player_state.get("health", "?"),
		player_state.get("max_health", "?"),
		player_state.get("stamina", "?"),
		player_state.get("max_stamina", "?"),
		enemy_state.get("health", "?"),
		enemy_state.get("max_health", "?"),
		world_state.get("turn", "?"),
	]


func _render_events(events: Array) -> void:
	var lines: Array[String] = []
	for event in events:
		var message := str(event.get("message", ""))
		if message != "":
			lines.append(message)
	log_label.text = "\n".join(lines.slice(max(0, lines.size() - 2), lines.size()))


func _play_event_hooks(events: Array) -> void:
	for event in events:
		var animation := str(event.get("animation", ""))
		if animation == "attack" or animation == "heavy_attack":
			var tween := create_tween()
			tween.tween_property(player_mesh, "scale", Vector3(1.25, 1.0, 1.25), 0.08)
			tween.tween_property(player_mesh, "scale", Vector3.ONE, 0.12)
		elif animation == "block":
			var tween := create_tween()
			tween.tween_property(player_mesh, "rotation_degrees:y", 20.0, 0.08)
			tween.tween_property(player_mesh, "rotation_degrees:y", 0.0, 0.08)
		elif animation == "dodge":
			var original := player_mesh.position
			var tween := create_tween()
			tween.tween_property(player_mesh, "position", original + Vector3(1.0, 0.0, 0.0), 0.08)
			tween.tween_property(player_mesh, "position", original, 0.12)
		elif animation == "reject":
			var tween := create_tween()
			tween.tween_property(enemy_mesh, "scale", Vector3(1.0, 0.75, 1.0), 0.08)
			tween.tween_property(enemy_mesh, "scale", Vector3.ONE, 0.12)


func _sync_mesh(mesh: MeshInstance3D, position_payload: Dictionary) -> void:
	mesh.position = Vector3(
		float(position_payload.get("x", 0.0)),
		float(position_payload.get("y", 0.0)) + 1.0,
		float(position_payload.get("z", 0.0))
	)


func _build_arena() -> void:
	floor_mesh = MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(28, 0.2, 28)
	floor_mesh.mesh = box
	floor_mesh.position = Vector3(0, -0.1, 12)
	add_child(floor_mesh)

	player_mesh = MeshInstance3D.new()
	var capsule := CapsuleMesh.new()
	capsule.radius = 0.45
	capsule.height = 1.8
	player_mesh.mesh = capsule
	var player_material := StandardMaterial3D.new()
	player_material.albedo_color = Color(0.2, 0.55, 1.0)
	player_mesh.material_override = player_material
	add_child(player_mesh)

	enemy_mesh = MeshInstance3D.new()
	var enemy_box := BoxMesh.new()
	enemy_box.size = Vector3(1.1, 1.8, 1.1)
	enemy_mesh.mesh = enemy_box
	var enemy_material := StandardMaterial3D.new()
	enemy_material.albedo_color = Color(0.95, 0.25, 0.2)
	enemy_mesh.material_override = enemy_material
	add_child(enemy_mesh)
