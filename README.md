# Substance Designer MCP

**The first MCP (Model Context Protocol) integration for Adobe Substance 3D Designer.**

Control Substance Designer from any MCP-compatible AI client (Claude Code, Claude Desktop, Cursor) — create graphs, build nodes, connect them, set parameters, generate full PBR material graphs from a single prompt.

> **Fork notice** — This repository is a fork of
> [matthieuhuguet/substance-designer-mcp](https://github.com/matthieuhuguet/substance-designer-mcp),
> originally created by **Matthieu Huguet ([@matthieuhuguet](https://github.com/matthieuhuguet) / ZenRay)**.
> All credit for the original plugin, bridge server, recipe engine and documentation goes to him.
> This fork, maintained by [@yang1190](https://github.com/yang1190), adds **Substance 3D Designer 16.0.x** support
> (function graphs, SDF, Shape splatter v2, OpenPBR) and several bug fixes — see
> [What's new in this fork](#whats-new-in-this-fork-sd-16) and the [CHANGELOG](CHANGELOG.md).

---

## What it does

- **Natural language → SD graph**: "Create a cracked concrete material" → 44-node PBR graph with height, normal, roughness, AO, baseColor, metallic outputs
- **79 built-in material recipes**: pro-grade materials using the same node architecture as professional SD artists
- **44 MCP tools**: get scene info, create/delete graphs, create nodes, connect nodes, set parameters, build full materials in one call, function graphs and SDF scenes (SD 16)
- **Library node support**: Clouds, Cells, Perlin Noise, Polygon, Edge Detect, Flood Fill, Multi-Directional Warp, etc.
- **Custom Library folders**: your own / third-party `.sbs` packages (SD's Library watched paths, `add_library_path`) are indexed and usable like built-in nodes
- **Thread-safe**: All SD API calls dispatched to Qt main thread via Signal/Slot queued connection

---

## What's new in this fork (SD 16)

Tested on **Substance 3D Designer 16.0.5** (Python 3.13, PySide6 6.8); SD 15.x remains supported.

**SD 16 compatibility & fixes**
- Library nodes are resolved by graph identifier from `<SD>/resources/packages` and loaded on demand. The original hard-coded `pkg:///x?dependency=N` URLs only worked when a package already depended on that library (on a fresh SD 16 session, 21 of 44 `pro_granite` nodes failed). The current (non-legacy) version of each node is preferred, and graphs stored in package folders resolve too — all 491 Library graphs instantiate.
- Output nodes get real usages (`baseColor`, `normal`, ...) so the 3D view picks them up.
- Graph output size is set as *Absolute* (it was "relative to parent", so 1024 requests produced 8192×8192).
- SD API errors (`APIException` derives from `BaseException`) are now reported instead of silently returning `{}`.
- PySide6 is imported natively; `mcp` pinned below 2.0 (FastMCP API).

**New SD 16 features**
- **Material model**: new graphs use OpenPBR v1.1 (`material_model` option, `list_material_models`).
- **OpenPBR outputs**: identifiers and dual usages copied from SD's OpenPBR template (43 channels incl. coat, fuzz, transmission, subsurface, thin film, emission).
- **Function graphs**: `build_function_graph` writes the function of any node parameter — pixel processor, value processor, 3D viewer, Shape splatter v2, mapper — from a JSON descriptor.
- **SDF**: `list_sdf_functions`, `build_sdf_scene` (3D viewer renders: beauty, depth, normals, material ID…) and `set_shape_splatter_sdf` (scatter custom SDF shapes, per-shape variation via `shape.id`).
- Knowledge base: Shape splatter v2 + mappers, Grid atlas, Angle to vector, 3D viewer, function-graph and SDF conventions.

**Validation on 16.0.5**: 79/79 material recipes and 8/8 heightmap styles build with 0 node and 0 connection failures; SDF scenes, SDF rock scattering and pixel processor functions render correctly.

---

## Architecture

```
AI Client (Claude / Cursor)
        │  stdio (MCP protocol)
        ▼
sd_mcp_bridge.py  (FastMCP server, Python 3.12)
        │  TCP localhost:9881 (length-prefix framing)
        ▼
SD plugin package plugin/  (runs inside SD: Python 3.11 on SD 15 / 3.13 on SD 16)
        │  sd.api
        ▼
Adobe Substance 3D Designer 15.x / 16.0.x
```

The bridge and plugin communicate with a simple length-prefix framing protocol: `[4-byte big-endian length][JSON payload]`. Each command uses a fresh TCP socket — no persistent connection, no stale state.

---

## Requirements

- **Adobe Substance 3D Designer 16.0.x** (tested on 16.0.5) or **15.x** (tested on 15.0.3)
- **Python 3.12+** for the bridge (managed via [uv](https://github.com/astral-sh/uv))
- **uv** package manager: `pip install uv` or `winget install astral-sh.uv`
- An MCP-compatible client: [Claude Code](https://claude.ai/code), [Claude Desktop](https://claude.ai/desktop), or [Cursor](https://cursor.sh)

---

## Installation

### Step 1 — Install the SD Plugin

Copy the `plugin/` folder contents to your SD user scripts directory:

**Windows:**
```
%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins\sd_mcp_plugin\
```

The directory must contain:
```
sd_mcp_plugin/           ← copy every .py file from plugin/
├── __init__.py          ← SD entry points (initializeSDPlugin / uninitializeSDPlugin)
├── common.py            ← shared imports, constants, helpers, SDError
├── transport.py         ← Qt main-thread dispatcher + TCP server (port 9881)
├── handler.py           ← CommandHandler: command table built from the mixins below
├── core.py              ← SD helpers: lookup, values, parameters, usages, material model
├── library.py           ← Library node resolution (built-in + custom folders, non-legacy first)
├── library_paths.py     ← custom Library folders: SD project files, plugin config, env var
├── scene_tools.py       ← scene / package / graph tools, diagnostic
├── node_tools.py        ← node / connection / parameter tools, arrange_nodes
├── builders.py          ← batch graph builder, recipe builders
├── function_graphs.py   ← function graphs, SDF, Shape splatter v2 (SD 16+)
├── render.py            ← render_outputs / export_outputs / validate_library
├── recipes.py           ← 79 material recipes + 8 heightmap styles
└── sd_documentation.py  ← embedded knowledge base (list_documentation)
```

When updating, copy **all** files and delete `__pycache__/`, then restart SD.

SD auto-loads all plugins from `sduserplugins/` on startup. No additional configuration needed.

### Step 2 — Install the Bridge Server

```bash
cd server/
uv sync   # installs mcp[cli] into .venv
```

Or with pip:
```bash
pip install "mcp[cli]>=1.4.1,<2"   # bridge uses the FastMCP v1 API
```

### Step 3 — Configure Your MCP Client

**Claude Code** (`~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "substance_designer": {
      "command": "C:\\Users\\YOUR_USERNAME\\.local\\bin\\uv.exe",
      "args": [
        "run",
        "--directory",
        "C:\\PATH\\TO\\substance-designer-mcp\\server",
        "python",
        "sd_mcp_bridge.py",
        "--port",
        "9881"
      ]
    }
  }
}
```

See `config/` folder for Claude Desktop and Cursor examples.

### Step 4 — Start SD before your AI client

**SD must be running before the MCP bridge starts.** The plugin binds TCP port 9881 on SD startup. If SD is not running when Claude/Cursor launches, the bridge will fail to connect.

---

## Usage

Once connected, you can ask your AI client to:

```
Build a weathered steel material with surface oxidation
```
```
Create a cliff heightmap with high detail and disorder
```
```
Make a new graph called MyRock, add a clouds node and a slope blur, connect them
```
```
List all available material recipes
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `get_scene_info` | List all open packages and graphs |
| `create_graph` | Create a new compositing graph |
| `get_graph_info` | Get all nodes and connections in a graph |
| `list_node_definitions` | Search available node types |
| `create_node` | Create an atomic node (blend, levels, blur, etc.) |
| `create_instance_node` | Create a library node (Clouds, Cells, Perlin, etc.) |
| `create_output_node` | Create a PBR output (baseColor, normal, height, etc.) |
| `connect_nodes` | Connect two nodes via their ports |
| `disconnect_nodes` | Remove a connection |
| `set_parameter` | Set a node parameter |
| `get_node_info` | Get ports and parameters of a node |
| `delete_node` | Delete a node |
| `move_node` | Reposition a node |
| `duplicate_node` | Duplicate an atomic node |
| `delete_graph` | Delete a graph from a package |
| `open_graph` | Open a graph in the SD editor |
| `save_package` | Save the package to disk |
| `execute_sd_code` | Execute arbitrary Python in SD's context |
| **`build_material_graph`** | **Build a full PBR material in one call** |
| **`build_heightmap_graph`** | **Build a heightmap-only graph in one call** |
| **`list_recipes`** | **List all 79 available material recipes** |
| `list_material_models` | SD 16+: list material models (OpenPBR, Adobe Standard Material, USD Preview Surface) |
| `list_function_nodes` | Atomic + library nodes usable in function graphs |
| `build_function_graph` | Build the function graph of any node parameter in one call (pixel processor, 3D viewer, Shape splatter v2...) |
| `get_function_graph_info` | Inspect a parameter's function graph |
| `list_sdf_functions` | SD 16+: the 52 SDF primitives / operators / transforms / materials with ports |
| **`build_sdf_scene`** | **SD 16+: build an SDF scene and render it with 3D viewer node(s) (beauty, depth, normals, material ID...)** |
| **`set_shape_splatter_sdf`** | **SD 16+: scatter a custom SDF shape with Shape splatter v2** |
| **`render_outputs`** | **Compute a graph and return per-output stats + PNG thumbnails (images) so the AI can check its result** |
| `export_outputs` | Compute and save output textures (png / tga / exr / tif / jpg) |
| `validate_library` | Instantiate every Library graph (batched) — health check after an SD update (`source='custom'` for custom folders) |
| `get_library_nodes` | Search built-in + custom Library graphs (`source`: all / builtin / custom / loaded; matches identifier, label, category) |
| `list_library_paths` | Every folder scanned for `.sbs` packages, where it comes from, packages / graphs found |
| **`add_library_path`** | **Permanently add a folder of `.sbs` packages (persistent config, survives plugin / SD updates)** |
| `remove_library_path` | Remove a folder (a folder from SD's own settings is ignored instead) |
| `rescan_library` | Re-index now (normally automatic within ~2 s) |
| `close_package` | Close a package (refuses unsaved changes unless `force`) |
| **`get_recipe_info`** | **Get details about a specific recipe** |
| **`apply_recipe`** | **Apply a recipe to an existing graph** |

### Material Recipes

```python
build_material_graph(graph_name="MySteel", recipe_name="pro_steel")
# → 37-node PBR graph: height + normal + roughness + AO + baseColor + metallic

build_heightmap_graph(graph_name="CliffHM", style="cliff", detail_level=3, scale=5.0, disorder=0.5)
# → 9-node heightmap graph
```

**Pro recipes (37–44 nodes, professional architecture):**
`pro_granite`, `pro_limestone`, `pro_sandstone`, `pro_basalt`, `pro_slate`,
`pro_steel`, `pro_iron`, `pro_copper`,
`pro_concrete`, `pro_concrete_aged`, `pro_concrete_smooth`

**Core materials:**
`steel`, `iron`, `copper`, `gold`, `silver`, `aluminum`, `brass`,
`granite`, `marble`, `sandstone`, `limestone`, `slate`, `basalt`,
`wood`, `wood_oak`, `moss`, `bone`, `leather`, `fabric_cotton`, `fabric_silk`, `fabric_wool`, `fabric_denim`, `fabric_burlap`,
`sand`, `mud`, `gravel`, `clay`, `soil`,
`ice`, `snow`, `frost`, `water`,
`diamond`, `ruby`, `sapphire`, `emerald`, `amethyst`,
`concrete`, `brick`, `lava`, `asphalt`, `plaster`, `tile`, `painted_metal`, `carbon_fiber`, `terracotta`, `obsidian`, ...

**Heightmap styles:**
`cliff`, `rock`, `sand`, `cracked`, `mud`, `mountain`, `cobblestone`, `terrain`

---

## Custom Library folders

The plugin indexes `.sbs` packages outside SD's install, so graphs from your own or third-party libraries work everywhere a library node is accepted (`create_instance_node`, batch `library_keyword` / `resource_url`, recipes).

Folders come from, in this order:

| Source | Where | Notes |
|---|---|---|
| `builtin` | `<SD>/resources/packages` | top level only, as before |
| `sd_project` | SD's own Library watched paths — *Edit > Preferences > Projects > Library*, read from `%LOCALAPPDATA%/Adobe/Adobe Substance 3D Designer/<major.minor>/user_project.sbsprj` (+ `default_project.sbsprj`, projects listed in `default_configuration.sbscfg`) | recursion / enabled / exclude pattern honoured; URL aliases (`sbs://`, custom aliases) resolved |
| `plugin_config` | `add_library_path(path, recursive=True)` → `%LOCALAPPDATA%/Adobe/Adobe Substance 3D Designer/sd_mcp/library_paths.json` | outside the plugin folder and not tied to an SD version: survives plugin updates and SD upgrades |
| `env` | `SD_MCP_LIBRARY_PATHS` (separated by `;` on Windows, `:` elsewhere; end a folder with `*` to scan it recursively) | |

```python
list_library_paths()                       # folders, source, recursion, packages / graphs found
add_library_path("D:/SD/MyLibrary")        # persistent; recursive by default
get_library_nodes(source="custom")         # label, category, description, path of each graph
get_library_nodes(filter_text="Tom Jacobs")  # also matches labels and categories
create_instance_node(resource_url="FloodFills")          # identifier
create_instance_node(resource_url="Flood Fills")         # Library label
create_instance_node(resource_url="Rocks.sbs#RockSharp_001")   # qualified: package file + identifier
create_instance_node(resource_url="D:/libs/rocks.sbs#rock_a")  # any .sbs, even outside library folders
```

- New or edited `.sbs` files in custom folders are picked up automatically (checked at most every 2 s); `rescan_library()` forces it.
- On an identifier collision the visible built-in graph wins; the custom copy is listed with a qualified URL (`File.sbs#identifier`, field `shadowed_by`). Keyword (prefix / substring) matching prefers built-in graphs, so adding a library never changes what the recipes get.
- A package that uses custom nodes references them by **relative path** when saved (SD's default *path storage: relative*): keep the library at a fixed location.
- `remove_library_path` on a folder that comes from SD's settings makes the plugin ignore it; SD's own settings are never modified.

## SD 16.0.x Notes

- Library nodes are resolved by **graph identifier** from `<SD>/resources/packages` and loaded on demand. Pass `clouds_2`, `pkg:///clouds_2` or a full URL — `?dependency=N` UIDs are session-specific and no longer required.
- When an identifier exists in several files, the plugin picks the version shown in SD's Library (legacy copies are hidden and have different port names, e.g. legacy `clouds_2` outputs `Clouds_2`).
- Output nodes now get real **usages** (`baseColor`, `normal`, `roughness`, ...) so the 3D view picks them up.
- New graphs use the **OpenPBR v1.1** material model by default; pass `material_model` (`adobe_standard_material_v4_0`, `usd_preview_surface`, or `""` for Undefined) to `create_graph` / `build_material_graph` / `build_heightmap_graph` / `create_batch_graph`.
- SD 16 ships PySide6 6.8 on its own `sys.path`; the plugin imports it natively and only falls back to path injection on older builds.
- **OpenPBR outputs**: with an OpenPBR graph, outputs get the identifiers and dual usages of SD's own OpenPBR template (`base_metalness` = `metalness` + `metallic`, `specular_roughness` = `specularRoughness` + `roughness`, plus coat / fuzz / transmission / subsurface / thin-film / emission channels).
- **Function graphs**: `build_function_graph` writes the function graph of any parameter from a JSON descriptor. Plain numbers become `const_*` nodes automatically (function inputs cannot be set directly), `"$pos"` / `"shape.id"` become variable getters.
- **SDF**: `build_sdf_scene` renders SDF scenes with the 3D viewer; `set_shape_splatter_sdf` scatters SDF shapes with Shape splatter v2. Z is up; each SDF outputs a signed distance.
- Validated on 16.0.5: all 79 material recipes and 8 heightmap styles build with 0 node failures and 0 connection failures; all 491 graphs visible in the Library instantiate.

### Example — SDF scene

```json
build_sdf_scene(graph_name="Knob", outputs=["beauty", "depth"], output="mat", nodes=[
  {"alias": "base", "type": "cube",   "inputs": {"size": [0.6, 0.6, 0.2], "rounding": 0.03, "center_position": [0, 0, 0.1]}},
  {"alias": "ball", "type": "sphere", "inputs": {"radius": 0.22, "center_position": [0, 0, 0.3]}},
  {"alias": "u",    "type": "union_smooth", "inputs": {"sdf_1": "@base", "sdf_2": "@ball", "smoothness": 0.08}},
  {"alias": "mat",  "type": "set_material", "inputs": {"scene": "@u", "basecolor": [0.75, 0.55, 0.2], "metalness": 1.0, "roughness": 0.3}}
])
```

---

## Critical Rules (SD 15.x)

These are hard constraints of the SD 15.x API — violating them hangs or crashes SD:

- **ONE tool call at a time** — never parallel calls to SD tools
- `SDUsage.sNew()` **hangs SD 15 permanently** — only used on SD 16+ (verified OK on 16.0.5)
- `newNode(unknown_definition)` **hangs SD 15 permanently** — plugin validates before calling
- ~~`arrange_nodes()` destroys all connections~~ — not true: it only moves nodes (verified on SD 16.0.5, connections and outputs unchanged). Since plugin 3.8.0 it lays the graph out by data flow
- Library node outputs are **never** `"unique_filter_output"` — always call `get_node_info` first
- `directionalwarp` warp-map port = `"inputintensity"` (NOT `inputgradient`)
- Wrong port ID in `connect_nodes` = crash — plugin validates before calling SD

---

## Known Library Node Ports (SD 15.0.3, unchanged on 16.0.5)

| Node | Output | Key Inputs |
|------|--------|-----------|
| `clouds_2` | `output` | `scale`, `disorder` |
| `cells_1` | `output` | `scale`, `disorder` |
| `perlin_noise` | `output` | `scale`, `disorder` |
| `polygon_2` | `output` | `Sides`, `Scale`, `Gradient` |
| `gradient_linear_1` | `Simple_Gradient` | `Tiling`, `rotation` |
| `gradient_axial` | `output` | `point_1`, `point_2` |
| `slope_blur_grayscale_2` | `Slope_Blur` | `Samples`, `Source`, `Effect` |
| `blur_hq_grayscale` | `Blur_HQ` | `Intensity`, `Source` |
| `non_uniform_blur_grayscale` | `Non_Uniform_Blur` | `Intensity`, `Anisotropy`, `Source` |
| `edge_detect` | `output` | `edge_width`, `tolerance`, `input` |
| `flood_fill` | `output` | `mask` |
| `flood_fill_to_gradient_2` | `output` | `angle`, `input`, `angle_input` |
| `flood_fill_to_grayscale` | `output` | `luminance_random`, `input` |
| `multi_directional_warp_grayscale` | `output` | `intensity`, `directions`, `input`, `intensity_input` |
| `highpass_grayscale` | `Highpass` | `Radius`, `Source` |
| `histogram_scan` | `Output` | `Position`, `Contrast`, `Input_1` |
| `invert_grayscale` | `Invert_Grayscale` | `Source` |
| `crystal_1` | `output` | `scale`, `disorder` |

---

## Testing

Two levels of tests, both need Substance Designer running with the plugin loaded:

```bash
python -m unittest tests/test_offline.py # offline checks, no SD needed (also run by GitHub Actions)
python tests/test_connection.py          # is the plugin reachable on port 9881?
python tests/run_regression.py --quick   # ~2 min smoke test
python tests/run_regression.py           # full suite (~15 min on SD 16.0.5)
```

`test_offline.py` needs no Substance Designer: it checks the syntax of every file, the custom Library path logic (SD `.sbsprj` parsing with URL aliases, plugin config, env var, recursive scan with exclude patterns, `.sbs` header parsing), the recipe structure (aliases, connections, outputs), and validates every recipe connection port and parameter id against `tests/data/sd_node_ports.json` — a snapshot of the real node definitions taken from SD with `python tests/update_port_snapshot.py` (rerun it after an SD update). With the `mcp` package installed it also checks the bridge tools. `.github/workflows/ci.yml` runs it on every push.

`run_regression.py` uses only the Python standard library and talks to the plugin's TCP port directly. It builds everything in a fresh unsaved package (closed at the end) and checks:

| Section | What is checked |
|---|---|
| recipes / heightmaps | every recipe builds with 0 node / 0 connection failures; height, base color, normal and roughness are not uniform; height is not low-contrast (`render_outputs` statistics) |
| performance | a recipe that takes more than 10 s to render at 256 px |
| library | every graph visible in SD's Library instantiates (`validate_library`) |
| custom_library | the built-in root is indexed; every visible graph in custom Library folders instantiates (`validate_library(source='custom')`) |
| sd16 | OpenPBR identifiers / dual usages, SDF scene, Shape splatter v2 SDF rock, pixel-processor function |

Known problems live in `tests/regression_baseline.json`: they are reported as **KNOWN** and do not fail the run; a listed problem that passes is reported as **FIXED** (remove it from the baseline). Any other failure is **FAIL** and the script exits with code 1. Reports (Markdown + JSON with all statistics) are written to `tests/reports/`.

The first run on SD 16.0.5 found 12 recipes with flat / low-contrast outputs and 3 slow fabric recipes; all were fixed in plugin 3.7.0 and the baseline is now empty (latest full run with plugin 3.10.0: 102 pass, 0 known, 0 fail).

---

## Troubleshooting

**Bridge can't connect to SD:**
- Make sure SD is running and fully loaded before launching your AI client
- Check SD logs: `%LOCALAPPDATA%\Adobe\Adobe Substance 3D Designer\log.txt` (look for `[SD-MCP]`)
- Verify the plugin is in the correct `sduserplugins` directory

**SD hangs after a command:**
- A bad node definition was likely used. Restart SD.
- The plugin validates node definitions before calling SD, but library nodes need correct `pkg://` URLs.

**Wrong port:**
- Plugin listens on **9881** by default. Bridge must use `--port 9881`.

**Plugin not loading:**
- Delete `__pycache__/` in the plugin directory and restart SD.

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Authors & Credits

- **Original author**: **Matthieu Huguet — [matthieuhuguet](https://github.com/matthieuhuguet)** / **[ZenRay](https://github.com/ZenRay)**, who built the first MCP integration for Substance Designer ([original repository](https://github.com/matthieuhuguet/substance-designer-mcp)).
- **SD 16 fork**: maintained by **[yang1190](https://github.com/yang1190)** — Substance 3D Designer 16.0.x support, function graphs / SDF / OpenPBR features and bug fixes listed above.

Pro recipe architecture based on deep analysis of professional Substance Designer node graph patterns: clouds_2 → slope_blur → edge_detect → flood_fill → multi_directional_warp → directionalwarp chains.

---

## Contributing

PRs welcome. Key areas for improvement:
- More material recipes
- Color graph support (currently height/grayscale focused)
- Windows + macOS path handling for plugin install
- Auto-install script for the SD plugin

Before opening a PR run `python -m unittest tests/test_offline.py` (also run by CI) and, with SD open, `python tests/run_regression.py --quick`.
