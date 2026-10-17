shader_type spatial;
render_mode unshaded, cull_disabled;

// Full side-by-side frame: left half goes to the left eye, right half to the right eye.
// Mipmapped + anisotropic: the frame is usually shown smaller than its pixel size in the
// headset, and plain bilinear sampling then shimmers and aliases text.
uniform sampler2D tex : source_color, filter_linear_mipmap_anisotropic;
uniform bool swap_eyes = false;
uniform bool eye_debug = false;  // tint the right eye red, to check each eye gets its own half

void fragment() {
	bool right = VIEW_INDEX == VIEW_RIGHT;
	if (swap_eyes) {
		right = !right;
	}
	// Keep each eye's samples a few texels inside its own half: mipmapped/anisotropic sampling
	// near the middle seam otherwise blends in the other eye's picture (artifacts at the edge).
	float margin = 6.0 / float(textureSize(tex, 0).x);
	float half_x = clamp(UV.x * 0.5, margin, 0.5 - margin);
	vec2 uv = vec2(half_x + (right ? 0.5 : 0.0), UV.y);
	ALBEDO = texture(tex, uv).rgb;
	if (eye_debug && VIEW_INDEX == VIEW_RIGHT) {
		ALBEDO = mix(ALBEDO, vec3(1.0, 0.0, 0.0), 0.5);
	}
}
