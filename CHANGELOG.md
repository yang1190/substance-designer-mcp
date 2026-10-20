# Changelog

All notable changes to the Substance Designer MCP Plugin are documented here.

---

## [1.2.0] — 2026-10-20 — Function graphs, SDF, OpenPBR outputs (SD 16)

### Plugin (v3.5.0)
- New module `plugin/function_graphs.py` (mixed into the command handler)
- `build_function_graph`: create/replace the function graph of any node parameter from a JSON descriptor — pixel processor `perpixel`, value processor `function`, 3D viewer `sdf_scene` / `camera_function` / `custom_output`, Shape splatter v2 `pattern_sdf_function` / `position_function` / `pattern_custom_function`, mapper `custom_function`. Plain values become `const_*` nodes (function inputs are connection-only), `$var` strings become `get_*` variable nodes, simple auto-layout
- `get_function_graph_info`, `list_function_nodes` (85 atomic + library functions indexed from `<function>` entries)
- `list_sdf_functions`: 52 SDF functions (20 primitives, 13 operators, 9 transforms, 5 materials, 5 maths) with ports
- `build_sdf_scene`: SDF scene + one 3D viewer per AOV (beauty, normal_ws/ts, position, distance, depth, color, material_id) + outputs
- `set_shape_splatter_sdf`: Shape splatter v2 SDF shapes (`shape_type` = SDF Function, bounding frame, `shape.id` variation)
- OpenPBR outputs: identifiers and dual usages copied from SD 16's OpenPBR template (43 channels); legacy graphs keep metallic/roughness usages. Usages use components RGBA and empty color space like SD's templates. Duplicate output identifiers get a numeric suffix
- Library graphs stored in package folders resolve (see 1.1.0)
- **Silent `{}` results fixed**: SD API errors (`APIException`) derive from `BaseException`, so every `except Exception` in the plugin missed them and the main-thread dispatcher returned an empty `{}` instead of the error. All handlers now catch `SDError = (Exception, APIException)` and the dispatcher reports `SD API error (APIException): ...`

### Bridge Server (v2.1.0)
- Tools: `list_function_nodes`, `list_sdf_functions`, `build_function_graph`, `get_function_graph_info`, `build_sdf_scene`, `set_shape_splatter_sdf`
- `build_material_graph` docstring now lists real recipe names (old list named recipes that do not exist, e.g. `steel`)

### Validation (SD 16.0.5)
- SDF scene (cube + sphere smooth union, cylinder cut, material) renders in beauty / depth / material ID
- Shape splatter v2 scatters an SDF bolt head; `sdf_color` carries `set_color`
- Pixel processor: clouds × UV gradient via `$pos`, `samplecol`, `vector4`, `mul`
- OpenPBR / Adobe Standard Material outputs verified; 79/79 recipes + 8/8 heightmaps still 0 failures

---

## [1.1.0] — 2026-10-20 — Substance 3D Designer 16.0.x support

### Plugin (v3.4.0)
- Tested on **SD 16.0.5** (Python 3.13.9, PySide6 6.8.6); SD 15.x still supported
- **Library nodes fixed**: resolved by graph identifier from `<SD>/resources/packages`, loaded on demand and released afterwards. Hard-coded `pkg:///x?dependency=N` URLs only resolved when a package already depended on that library, so on a fresh SD 16 session 21 of 44 `pro_granite` nodes failed
- Version selection: prefers the graph visible in SD's Library over hidden Legacy copies (e.g. `noise_clouds_2_v2.sbs` over `clouds_2.sbs`), matching the `output` port names used by the recipes
- Library graphs stored in package folders (e.g. SD 16 Constant nodes: `pkg:///float/constant_float`) now resolve; all 491 graphs visible in the 16.0.5 Library instantiate successfully
- `get_library_nodes` searches the whole built-in library (808 graphs on 16.0.5) and returns portable `pkg:///<identifier>` URLs
- Output nodes now get usages (`baseColor`, `normal`, `roughness`, `metallic`, `height`, `ambientOcclusion`, ...) on SD 16+
- New `material_model` option (default `openpbr_v1_1` on SD 16) for `create_graph`, `create_batch_graph`, `build_material_graph`, `build_heightmap_graph`; new `list_material_models` tool
- PySide6 imported natively first; path injection only as fallback
- **Output size fixed**: `$outputsize` is now set as Absolute. New graphs default to "Relative to parent", so `output_size_log2=10` produced 8192x8192 (clamped) instead of 1024x1024
- `diagnostic` reports Python version, SD major version, library index size
- Docs knowledge base: Shape splatter v2 (+ mappers), Grid atlas, Angle to vector, 3D viewer, SD 16 notes
- Recipes: library URLs converted to portable form

### Bridge Server (v2.1.0)
- `material_model` parameter on graph-building tools; `list_material_models` tool
- Pinned `mcp[cli]>=1.4.1,<2` (mcp 2.x renamed FastMCP)

### Tests
- Default port fixed to 9881 in `tests/test_connection.py` and `tests/test_mcp_stdio.py`

### Validation (SD 16.0.5)
- 79/79 material recipes and 8/8 heightmap styles: 0 node failures, 0 connection failures
- 78/78 full-PBR recipes get 6 outputs with usages + OpenPBR material model

---

## [1.0.0] — 2026-02-19 — First Public Release

### Plugin (v3.1.0)
- Complete MCP integration for Adobe Substance 3D Designer 15.x
- 16 MCP tools (11 core + 5 recipe/builder tools)
- Thread-safe Qt dispatch via Signal/Slot queued connection
- PySide6 path injection (SD ships its own PySide6, not in sys.path)
- Length-prefix TCP framing protocol (4-byte big-endian + JSON)
- Fresh-socket-per-command connection model (no stale state)

### Recipe System (v5.0 — 79 recipes)
- **Pro architecture family**: pro_granite, pro_limestone, pro_sandstone, pro_basalt, pro_slate, pro_steel, pro_iron, pro_copper, pro_concrete, pro_concrete_aged, pro_concrete_smooth (37–44 nodes each)
- **Core materials**: wood×5, rock×6, metal×7, organic×9, soil×5, water_ice×4, gems×5
- **Specialty**: concrete, brick, lava, asphalt, plaster, fabric, tile, specialty
- **Heightmap styles** (8): cliff, rock, sand, cracked, mud, mountain, cobblestone, terrain
- **MainShape** reconstruction (pro architecture, 11 nodes from live data)
- Pro node chain: clouds_2 → slope_blur×2 → edge_detect → flood_fill → flood_fill_to_gradient_2 → multi_directional_warp×2 → directionalwarp×3 → highpass → histogram_scan
- All 79 recipes validated: 0 port failures, 0 crashes

### Bridge Server (v2.0.0)
- BUG-B01: `_send_lock` no longer held across retry loop — prevents 360-second deadlock
- BUG-B03: Default port corrected to 9881 (was 9880)
- BUG-B04: `directionalwarp` warp-map port corrected to `inputintensity` (was `inputgradient`)
- BUG-B05: FastMCP lifespan set at constructor, not post-construction
- BUG-B06: `ctx: Context` kept for FastMCP 1.4.1+ compatibility
- BUG-B07: `None` results return `"{}"` not `"null"`; NaN/Inf handled via `_json_safe`
- BUG-B08: Retry logic applies to connection failures only, not SD operation timeouts
- Async serialization via `threading.Lock` + `asyncio.to_thread`

### Critical Bug Fixes (SD 15.x)
- `SDValueInt2/3/4` on float params crashes SD silently → `_infer_type` always returns float2/3/4 for lists
- `SDValueFloat` on enum/int SD properties crashes SD silently → `_coerce_type()` reads actual SD type
- `_set_node_params` reads property type via `getType().getId()` and coerces accordingly
- `build_heightmap_graph`: builders return dict, not tuple — fixed unpacking
- `SDPackage.deleteResource()` does not exist — correct API is `resource.delete()`

### Confirmed SD 15.0.3 API Facts
- Library node outputs ≠ `"unique_filter_output"` (each has its own ID)
- `SDUsage.sNew()` hangs SD 15 permanently — removed
- `newNode(unknown_def)` hangs SD 15 permanently — validated before call
- `arrange_nodes()` destroys all connections — use `move_node()` instead
- `directionalwarp` warp-map input = `inputintensity` (NOT `inputgradient`)

---

## Internal Versions (not publicly released)

- **v3.1.0** (2026-02-18): SD crash fixes, build_heightmap bug fix, SD API notes
- **v3.0.0** (2026-02-15): Full recipe engine, smart builder, 34 initial materials
- **v2.x.x** (2026-02-10): PySide6 injection, Signal/Slot dispatcher
- **v1.x.x** (2026-02-01): Initial prototype
