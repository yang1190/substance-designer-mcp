# Changelog

All notable changes to the Substance Designer MCP Plugin are documented here.

---

## [1.8.0] — 2026-10-21 — Claude skills for material work

### Skills (new, `sd-material-skills` plugin v1.0.0)
- `skills/sd-material-workflow`, `skills/sd-material-recipes`, `skills/sd-node-techniques`: Agent Skills (Chinese) distilled from the SD_Textures project — 3 work modes, `_build/` script framework, SD 16 / MCP pitfalls (Blend 4 = AddSub / 5 = Max / 6 = Min, Slope Blur and Tile Sampler enums, absolute output size, 16-bit format, 60 s timeout + async compute), 9 material categories, 13 technique stages
- The repo is a Claude Code plugin marketplace: `.claude-plugin/plugin.json` + `marketplace.json`
- `skills/packages/*.skill` for Claude.ai upload, rebuilt with `tests/build_skill_packages.py`
- Offline tests: SKILL.md frontmatter, packages in sync with sources, plugin manifests

---

## [1.7.1] — 2026-10-21 — create_graph defaults to 2048

### Plugin (v3.10.1) / Bridge Server (v2.3.1)
- `create_graph(output_size_log2=11)`: new graphs are created at an **absolute 2048x2048** instead of SD's 256x256 (relative to parent), matching `build_material_graph` / `build_heightmap_graph` / batch builders. At 256 the Flood Fill based nodes (e.g. Tom Jacobs `FloodFills` → `ShiftRocks`) only found a few tiny islands. `output_size_log2=0` keeps SD's default; the result reports `output_size`

---

## [1.7.0] — 2026-10-21 — Custom Library folders

### Plugin (v3.10.0)
- **Custom Library folders are indexed** next to `<SD>/resources/packages`, so graphs from your own / third-party `.sbs` packages work everywhere a library node is accepted (`create_instance_node`, batch `library_keyword` / `resource_url`, recipes). New module `plugin/library_paths.py` (pure Python, unit-tested offline) collects the folders from:
  - SD's own Library watched paths (*Preferences > Projects > Library*), parsed from `%LOCALAPPDATA%/Adobe/Adobe Substance 3D Designer/<major.minor>/user_project.sbsprj`, `default_project.sbsprj` and projects listed in `default_configuration.sbscfg` — `isrecursive`, `isenabled`, exclude patterns and URL aliases (`sbs://`, custom aliases, `$(PROJECT_DIR)`) are honoured. A folder added in SD is used automatically
  - a persistent plugin config `%LOCALAPPDATA%/Adobe/Adobe Substance 3D Designer/sd_mcp/library_paths.json` (outside the plugin folder and not tied to an SD version: survives plugin updates and SD upgrades)
  - the `SD_MCP_LIBRARY_PATHS` environment variable (`*` suffix = recursive)
- New commands / tools: `list_library_paths`, `add_library_path(path, recursive, label)`, `remove_library_path` (a folder from SD's settings is ignored instead; SD's files are never modified), `rescan_library`
- `get_library_nodes`: `source` filter (all / builtin / custom / loaded), `include_hidden`; filter text also matches Library label, category and tags; custom entries carry label, category, author, description, path and library root
- References: identifier (`FloodFills`), Library label (`Flood Fills`), or qualified `File.sbs#identifier` / `D:/libs/x.sbs#identifier` (any .sbs, even outside library folders)
- Collision rules: the visible built-in graph wins; a shadowed custom copy is listed with a qualified URL (`shadowed_by`). Prefix / substring keyword matching prefers built-in graphs, so adding a library never changes what the recipes resolve to (checked: the 22 recipe library keywords resolve identically)
- Changes on disk are detected automatically (new / edited `.sbs`, plugin config, SD project files; checked at most every 2 s); unchanged files are not re-read. Full index of 528 files: ~0.35 s
- Graph and function indexes now share one scan. Hidden detection reads only the graph's own `<attributes>` block — two built-in functions without attributes (`lexicographic_greater_than_vec2`, `argmax_float2_mask`) were wrongly marked hidden because a parameter's `hideInLibrary` leaked in
- `validate_library(source=...)`; its cleanup never unloads packages the user had open
- `diagnostic` lists every enabled library root

### Bridge Server (v2.3.0)
- Tools `list_library_paths`, `add_library_path`, `remove_library_path`, `rescan_library` (44 tools); `get_library_nodes` gains `source` / `include_hidden`; `validate_library` gains `source`

### Tests
- `test_offline.py`: 5 new tests (SD `.sbsprj` parsing with aliases and exclude patterns, version folder selection, plugin config round trip, env var, recursive scan, `.sbs` header parsing, qualified references) — 13 tests
- `run_regression.py`: new `custom_library` section (built-in root indexed; every visible graph of every custom folder instantiates)

### Verified on SD 16.0.5 with the Tom Jacobs CustomLibrary
- Built-in index identical to 3.9.0 (808 identifiers, same files, same hidden set, same preferred file for every identifier); 13 custom identifiers added
- Flood Fills, Shift Rocks, Add To Ground, Edge Variation, Push Edges, Rock Shelter 001, Rock Sharp 001, Simple Outputs instantiate by identifier, label and qualified reference; a test graph (Rock Sharp → Flood Fills / Push Edges, Rock Shelter colour) renders non-flat outputs
- A saved package references the custom packages by relative path (`../../../Documents/.../CustomLibrary/FloodFills.sbs`) — keep the library at a fixed location
- add / remove / ignore / auto re-index checked live
- Offline tests 13/13; full regression after deploying 3.10.0: **102 pass, 0 fail** (library sweep 499 graphs = 491 built-in + 8 custom; new custom_library section 3/3)

---

## [1.6.0] — 2026-10-20 — Code reorganisation

### Plugin (v3.9.0) — no behaviour change
- `plugin/__init__.py` (2755 lines) split into modules: `common.py` (imports, constants, helpers, `SDError`), `transport.py` (Qt dispatcher + TCP server), `handler.py` (`CommandHandler`), and feature mixins `core.py`, `library.py`, `scene_tools.py`, `node_tools.py`, `builders.py`; `__init__.py` now only holds the SD entry points and the module map
- The node-creation / connection loop that `create_batch_graph` and `apply_recipe` each had a copy of is now one `_populate_graph`; recipe overrides / offsets share `_recipe_variant`. `apply_recipe` now also returns `failed_nodes` and per-connection results
- `function_graphs.py` and `render.py` use the shared `SDError` / `_log` from `common.py`
- Removed dead code: `server/sd_node_recipes.py` (1322 lines, never imported), unused `BLEND_MODES`, `_library_cache`, `_QTimer`, `_resolve_lib_url`, unused imports; outdated version history moved out of the module docstring (see this file)
- pyflakes clean across `plugin/`, `server/sd_mcp_bridge.py` and `tests/`

### Verification
- Six recipes built with the old (3.8.0) and new (3.9.0) code give identical node/connection counts and identical output statistics; `apply_recipe`, `arrange_nodes`, SDF scene, diagnostic, documentation, `execute_code` and `validate_library` checked on SD 16.0.5
- Offline tests 8/8; full regression after deploying 3.9.0 on SD 16.0.5: **99 pass, 0 fail**; `tests/update_port_snapshot.py` regenerates an identical snapshot (only the plugin version changes)

### Housekeeping
- Deleted the test artefacts created during development (`SD_Textures/MCP_Dev/_mcp_tests`, temporary `sd_mcp_sd16_deptest.sbs`)

---

## [1.5.0] — 2026-10-20 — No more silent failures; offline CI

### Plugin (v3.8.0)
- **Parameter failures are reported**: `create_batch_graph`, `build_material_graph`, `build_heightmap_graph` and `apply_recipe` return `params_failed` and `param_issues` (`unknown_parameter` with the node's real parameter ids, or `set_failed: <error>`). Before, a misspelled parameter was silently ignored and the node kept its default
- System parameters (`$outputsize`, `$format`, `$randomseed`...) in batch descriptors are applied as Absolute values; they were silently skipped although the bridge docs used `$outputsize` as an example
- `set_parameter` coerces the value to the property's real type (a float on an enum/int crashes SD) and sets `$` parameters as Absolute
- `arrange_nodes`: verified on SD 16.0.5 that it never touched connections (50 before/after on pro_granite, identical outputs) — the "destroys all connections" warning was wrong and is removed from README, knowledge base and tool docs. It now lays the graph out left-to-right by data flow, outputs in the last column

### Bridge Server
- `.venv` path injection only on Windows (a Windows `.venv` in the checkout broke imports on Linux/macOS)
- `create_batch_graph` docs: check `params_failed` / `param_issues`

### Tests
- `tests/test_offline.py` (no SD): syntax, recipe structure, recipe ports and parameter ids against `tests/data/sd_node_ports.json`, bridge tools and image conversion. A mutation check (typo'd parameter, Legacy port name, unknown alias) fails all three relevant tests
- `tests/update_port_snapshot.py`: regenerates the port snapshot from a live SD (22 library + 8 atomic node types on 16.0.5)
- `.github/workflows/ci.yml`: runs the offline tests on every push / pull request
- `run_regression.py`: parameter failures count as FAIL
- Full run on SD 16.0.5 with plugin 3.8.0: **99 pass, 0 fail** (including the new parameter check — no recipe has an unapplied parameter); offline tests: 8/8 pass

---

## [1.4.0] — 2026-10-20 — Recipe fixes found by the regression suite

### Plugin (v3.7.0) — recipes
- **pro_granite / pro_limestone / pro_sandstone / pro_basalt / pro_slate**: `edge_detect` ran on the smooth macro shape, found almost no edges, and the whole flood-fill → warp → histogram chain collapsed to a near-black height (std ≤ 0.006). Islands now come from `cells_4` → `edge_detect` → `flood_fill` (per-island gradient + grayscale), mixed 50/50 with the macro shape, with crack lines multiplied in before the warps; histogram-scan contrast 0.6 → 0.3 to avoid clipping. Height std 0.19–0.20
- **gem_***: final levels input range 0.3–0.9 did not match the warp output (≈0–0.45) and clipped everything to the 0.6 floor; now 0.02–0.45 → 0.2–1.0 (height std 0.004 → 0.12)
- **carbon_fiber**: rebuilt on `weave_generator` (2×2 twill) + stretched-Perlin fiber streaks + warp/weft tint; the old cross-hatch was clipped to black by its levels node
- **obsidian**: stronger shell relief, less final blur, full output range, normal intensity 10 (`_make_recipe(normal_intensity=...)`)
- **fabric_***: fuzz noise `clouds_2` → `perlin_noise`. clouds_2 cost grows ~quadratically with scale (scale 72 = 32 s at 256 px on SD 16.0.5); fabric_silk 34.6 s → 0.9 s, velvet 24.7 s → 0.9 s, denim 17.2 s → 0.9 s
- **rock_* (6 recipes)**: one centred `polygon_2` (Tiling 1) → randomized `tile_random` lumps (pyramid for 6-sided rocks, paraboloid otherwise); `gradient_linear_1` → tileable `clouds_2`, removing the dark band along the top/bottom edges

### Plugin — tools
- **Library resolution bug**: a bare `pkg:///x` URL was matched against *any* loaded package. Once a hidden Legacy copy was loaded as a dependency (e.g. after `validate_library`), `cells_1` resolved to Legacy `cells_1.sbs` (output `Cells` instead of `output`) and 22 recipes lost a connection. Exact URL matching is now only used for `?dependency=` URLs; bare identifiers always go through the version ranking
- `render_outputs` recomputes once if an output has no texture after the first compute

### Tests (runner)
- New section `after_library_sweep`: rebuilds 5 recipes after the library sweep to catch state-dependent resolution bugs like the one above
- Final full run on SD 16.0.5 with plugin 3.7.0: **99 pass, 0 known, 0 fail** (79 recipes, 8 heightmaps, 491 Library graphs, 5 post-sweep rebuilds, 4 SD 16 feature checks)

### Tests
- Full run after the fixes: 82 pass, 11 fixed, 0 fail. `obsidian` returned no texture once in that run (engine hiccup) and passes on re-run (normal std 0.011, height std 0.066); `render_outputs` now recomputes in that case. Baseline emptied

---

## [1.3.0] — 2026-10-20 — Render/inspect tools and regression suite

### Plugin (v3.6.0)
- New module `plugin/render.py`
- `render_outputs`: computes a graph and returns, per output node, identifier, usages, size, pixel format, per-channel min/max/mean/std with `flat` / `low_contrast` flags, and a PNG thumbnail (base64). Reads the texture buffer directly (8/16-bit, 16F, 32F; LUM and RGBA verified on 16.0.5); grayscale thumbnails normalized to their own range
- `export_outputs`: compute and save output textures (png/tga/exr/tif/jpg) with a name pattern
- `validate_library`: batched instantiation of every visible Library graph in a throw-away package
- `close_package`: unload a package (refuses saved packages with unsaved changes unless `force`)
- `create_package` now returns `package_index`
- Knowledge base: workflow rule "verify with render_outputs"

### Bridge Server (v2.2.0)
- `render_outputs` returns the thumbnails as MCP image content (the AI client sees the images) plus the JSON statistics
- Tools `export_outputs`, `validate_library`, `close_package` (40 tools)

### Tests
- `tests/run_regression.py` (stdlib only): recipes, heightmaps, performance, library, SD 16 features; KNOWN/FIXED/FAIL against `tests/regression_baseline.json`; Markdown + JSON reports in `tests/reports/`
- First full run on SD 16.0.5: 79 recipes, 8 heightmaps, 491 Library graphs, 4 SD 16 feature checks. Baseline: 12 recipes with flat / low-contrast outputs, 3 slow fabric recipes

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
