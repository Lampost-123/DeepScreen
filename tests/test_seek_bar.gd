extends SceneTree
# Headless check of the video seek bar: aiming at 25% / 50% / 90% along the bar gives that
# fraction, aiming at the picture or below the bar gives none, and the seek command is URL-safe.
# Run: godot --headless --xr-mode off --path D:\vn3d-stable\viewer --script res://../tests/test_seek_bar.gd

var _done := false


func _process(_delta: float) -> bool:
	if not _done:
		_done = true
		_run()
	return true


func _aim(ctrl: XRController3D, target: Vector3) -> void:
	ctrl.global_position = Vector3(0, 0, 3.0)  # viewer's head, screen 3 m ahead (screen at origin)
	ctrl.look_at(target, Vector3.UP)


func _run() -> void:
	var m = load("res://main.gd").new()
	m.distance = 3.0
	m.width = 4.0
	m.aspect = 16.0 / 9.0
	m.mode = "sbs"
	m.media = true
	m._vlc_pass = "test"
	var screen := MeshInstance3D.new()
	root.add_child(screen)
	m._screen = screen
	m._build_seek_bar()
	m._vlc_length = 100.0
	m._layout_seek_bar()
	var ctrl := XRController3D.new()
	root.add_child(ctrl)
	var bar_y: float = m._seek_root.position.y
	var w: float = m._bar_width()
	var ok := true
	for frac in [0.25, 0.5, 0.9]:
		_aim(ctrl, Vector3(-w * 0.5 + w * frac, bar_y, 0))
		var hit: Dictionary = m._bar_hit(ctrl)
		var got: float = hit.get("frac", -1.0)
		print("aim %.2f -> %.3f" % [frac, got])
		ok = ok and absf(got - frac) < 0.01
	_aim(ctrl, Vector3(0, 0, 0))  # middle of the picture
	ok = ok and m._bar_hit(ctrl).is_empty()
	_aim(ctrl, Vector3(0, bar_y - 0.5, 0))  # well below the bar
	ok = ok and m._bar_hit(ctrl).is_empty()
	m._vlc_busy = true  # keep the command queued instead of sending it
	m._vlc_command("seek&val=%d%%25" % 37)
	print("queued: %s" % m._vlc_queue)
	ok = ok and m._vlc_queue == ["seek&val=37%25"]
	# Auto-hide: visible after interaction, hidden 3 s later, always visible while paused.
	m._vlc_state = "playing"
	m._show_seek_bar()
	var shown: bool = m._seek_root.visible
	m._vlc_http = HTTPRequest.new()  # _vlc_process needs it; nothing is sent (no request made)
	m._vlc_poll_left = 99.0
	m._vlc_process(3.5)
	var hidden: bool = not m._seek_root.visible
	m._vlc_state = "paused"
	m._update_seek_visibility()
	var paused_shown: bool = m._seek_root.visible
	print("auto-hide: shown %s, hidden after 3.5 s %s, shown while paused %s" % [shown, hidden, paused_shown])
	ok = ok and shown and hidden and paused_shown
	m._vlc_http.free()
	print("PASS" if ok else "FAIL")
	m.free()
