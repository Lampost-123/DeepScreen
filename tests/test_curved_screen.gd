extends SceneTree
# Headless check of the curved screen: for points on the curved mesh, a ray from the head
# through that point must hit back at the same UV. Run:
#   godot --headless --xr-mode off --path D:\vn3d-stable\viewer --script res://../tests/test_curved_screen.gd


var _done := false


func _process(_delta: float) -> bool:
	# Runs on the first frame, when nodes added to root are inside the tree.
	if not _done:
		_done = true
		_run()
	return true  # quit after this frame


func _run() -> void:
	var m = load("res://main.gd").new()
	m.distance = 3.0
	m.width = 4.0
	m.aspect = 16.0 / 9.0
	m.curved = true
	m.mode = "sbs"
	var screen := MeshInstance3D.new()
	root.add_child(screen)
	m._screen = screen
	var mesh: ArrayMesh = m._curved_mesh(m.width, m.width / m.aspect, m.distance)
	var verts: PackedVector3Array = mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	var uvs: PackedVector2Array = mesh.surface_get_arrays(0)[Mesh.ARRAY_TEX_UV]
	var head := Vector3(0, 0, m.distance)  # cylinder axis = viewer position in the screen frame
	var worst := 0.0
	var misses := 0
	for i in range(0, verts.size(), 7):
		# Aim slightly inside the edge so the top/bottom rows aren't exactly on the boundary.
		var target := verts[i] * Vector3(1, 0.98, 1)
		var hit: Dictionary = m._curved_hit(head, (target - head).normalized())
		if hit.is_empty():
			misses += 1
			continue
		var expect := Vector2(uvs[i].x, 0.5 + (uvs[i].y - 0.5) * 0.98)
		worst = maxf(worst, (hit["uv"] - expect).length())
	print("curved screen: %d vertices checked, %d misses, worst uv error %.5f" % [verts.size() / 7, misses, worst])
	print("PASS" if misses == 0 and worst < 0.002 else "FAIL")
	m.free()
