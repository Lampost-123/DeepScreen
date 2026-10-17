shader_type spatial;
render_mode unshaded, cull_disabled, blend_premul_alpha, depth_draw_never;

// One Ren'Py layer from vn3d_hook.rpy: color is premultiplied by alpha (drawn over black),
// mask holds alpha as gray. Opaque layers (backgrounds) have no mask.
uniform sampler2D color_tex : source_color, filter_linear_mipmap;
uniform sampler2D mask_tex : filter_linear_mipmap;
uniform bool has_mask = false;

void fragment() {
	ALBEDO = texture(color_tex, UV).rgb;
	ALPHA = has_mask ? texture(mask_tex, UV).r : 1.0;
}
