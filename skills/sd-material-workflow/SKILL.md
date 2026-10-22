---
name: sd-material-workflow
description: Use when building, iterating on, or breaking down a PBR material in Substance Designer (SD 16 + SD MCP) - production workflow, build-script framework, pitfall cheat sheet, verification and documentation conventions.
---

# SD Material Production Workflow (SD_Textures project)

Project root: E:/Work/PersonalProject/SD_Textures (on the device shell: $HOME/mnt/SD_Textures). Software: SD 16.0.x, driven through the user's own fork of the SD MCP plugin (mcp__remote-devices__substance_designer__*; the main tool is execute_sd_code).

Companion skills:
- sd-material-recipes: pick an approach and reference files by material category (rocky ground / cliffs / tiles / forest floor / desert / organic)
- sd-node-techniques: look up node techniques by production stage (single shapes, scattering, per-cell data, cutting planes, cracks, sand and mud, moss, water, normal / AO, BaseColor, Roughness)

## 0. Pick the mode first

| Mode | Trigger | Go to |
|---|---|---|
| A New | make an XX material, a reference image is given | Section 2 |
| B Iterate | the user gives feedback after looking at the SD 3D view or a screenshot | Section 3 |
| C Break down | analyze / break down the node flow of an existing .sbs | Section 4 |

Before starting:
1. project_search / project_read the project docs for similar materials (claude/sd-*.md) and the *_节点流程.md (node flow) files next to the .sbs
2. Read the matching category in sd-material-recipes to choose the approach and reference files
3. Confirm with AskUserQuestion: reference images, resolution, output spec (standard 6 channels or OpenPBR), whether to do only Height / Normal first

## 1. Hard rules (user preferences)

1. Every map is derived from the final height H_final: Normal, AO, curvature, BaseColor masks, Roughness masks. Per-cell IDs may come from Flood Fill (computed from a binarized height) or from channels warped in sync with the height; never color with intermediate masks that do not line up with the height
2. Pebbles, shards, weeds, moss clumps: build a single heightmap first, then scatter it randomly inside a mask with Tile Sampler (or Shape Splatter); do not generate them directly with Voronoi. Exception: densely packed materials where stones fill everything and press against each other (rubble fields, aggregate) may use the Cells + dilation approach
3. Only sbs:// built-in library nodes by default; custom libraries (Tom Jacobs CustomLibrary, the MV series) need the user's approval and must be copied together with their dependencies
4. Tileable; 2048² Absolute; 16-bit
5. Get the clay model (Height + Normal) approved before working on color

## 2. Mode A: new material

### 2.1 Reference analysis (quantified)
- Analyze the reference in the cloud container with Python:
  - Height: mean / std / skew; FFT radial energy distribution (e.g. share of 16–32 cycles/tile) to infer the rock block size
  - Color: take lit pixels above a luminance threshold and run k-means(5) on chromaticity (r,g,b)/sum to get color families and their shares. Lighting is baked into the reference, so take chromaticity only and re-assign luminance to PBR ranges (copying the soil luminance from a reference comes out too dark)
  - Split regions by saturation thresholds (e.g. < 0.12 is rock, > 0.22 is sand)
- If there is a clay (height render) reference, compare against it; color comparison comes later

### 2.2 Package and graph setup
- The graph $outputsize must get setPropertyInheritanceMethod(prop, Absolute) before setting (11,11); relative to parent it ends up at 8192
- Use 1024 (10) while tuning for speed; HBAO-based masks must be re-checked at 2048 at the end
- Set $format to Absolute + 16-bit on key height-chain nodes, otherwise 8-bit contour steps appear
- Since plugin v3.10.1 create_graph defaults to 2048; a 256 graph makes Flood Fill find only a few tiny islands

### 2.3 Build-script framework (one _build/ per material)
```
<material>/_build/
  h.py        helper library: B builder (alias -> node, auto layout), atom() / lib() / wire(), levels / blend / blur / hscan / gradient, preview(), preview_async(), clean_outputs()
  cfg.py      every tunable (layer tables LAYERS / PASSES, palettes, strengths)
  s1_*.py ... stages: single shapes -> scatter -> compose -> derived maps -> outputs -> frames
  build_all.py / run.py  delete all non-output nodes, then rebuild everything in STAGES order
  s5_frames.py  layout + frames + comments
  s6_export.py  async export
  nodes.json  alias -> node id
<material>/_preview/  preview pngs and _done.txt
```
- Templates to copy: StoneGroundA/_build/ (newest, cleanest), Rocky_Ground/_build/
- Each execute_sd_code call is a fresh namespace: exec(open(h.py, encoding='utf-8').read()) first
- **Always rebuild everything with build_all**: re-running a single stage breaks the connections of later stages or fails on undefined functions
- Aliases must be unique: a duplicate alias makes _reg delete an old node that is still in use and the whole layer outputs 0; purge is prefix matching (m_b also deletes m_band)
- Instance nodes have no description field; keep aliases in nodes.json
- Library nodes need loadUserPackage(resources/packages/xxx.sbs) first; graph ids in noise_* packages have no prefix (noise_perlin_noise maps to perlin_noise); HBAO lives in hbao_2.sbs with id hbao

### 2.4 Clay Height (step by step, preview every step)
1. Ground / macro relief -> 2. Large rocks / main body -> 3. Medium rocks -> 4. Small rocks -> 5. Gravel / fine grit -> 6. Surface detail -> 7. Floor fill / anti-aliasing -> H_final
- Preview each step: top-down grayscale, shaded clay with cast shadows (clay.py, low-angle light), oblique displacement view (oblique.py, CROP=x,y,w to zoom, close to the SD 3D view), profiles (profile.py)
- To judge whether rocks stand on the ground, look at height relative to the local ground (H - Blur(H)), not absolute height; macro relief and stacking lift both eat the rocks' relative height
- Measure clipping at every level (16-bit graphs clip at 1), p99.5 statistics

### 2.5 Derived maps (all from H_final)
- Normal: Height to Normal World Units (surface 200–300 cm, depth 20–60 cm depending on the material; DirectX) or a plain Normal at intensity 8–15
- AO: HBAO (world units); inside BaseColor use a local HBAO computed on a high-passed height, not the World Units AO (it darkens whole hollows)
- Curvature: Curvature Smooth at two scales (blur the height first, then compute the normal = wide scale)
- Layer masks = height difference between two adjacent steps of the compose chain + a Levels threshold

### 2.6 BaseColor -> Roughness
- See the BaseColor / Roughness sections of sd-node-techniques; finish with PBR Albedo Safe Color; sRGB darks not below about 30–40
- Prefer Roughness = inverse Levels mapping of the Albedo grayscale + the same set of patterns, so it correlates with color

### 2.7 Wrap-up
- clean_outputs removes temporary outputs; walk back from the real outputs and delete nodes not connected to any output
- s5_frames: group by alias, frame titles in Chinese and English, descriptions state the method and key parameters (read from cfg); comments on key nodes; only setPosition, never arrange_nodes (it breaks connections)
- Check: every node inside a frame, frames do not overlap, connection count and output wiring unchanged
- Export 2048 to <material>/Textures or Output; verify tiling (seam difference no larger than the difference between neighbouring interior pixels)

### 2.8 Documentation
- Write or update the project doc claude/sd-<material>.md (project_write): file and graph info, build scripts, flow structure, key parameter table, version log (feedback -> cause -> fix -> measured result), pitfalls, known gaps / next steps
- Add newly found general pitfalls to section 5 of this skill as well (propose a skill update)

## 3. Mode B: iterate on user feedback
1. **Diagnose before changing**: turn the feedback into something measurable. E.g. hard edge lines -> count, per column on both sides of the seam, how consistently the normal sign agrees; black spots -> check dark BaseColor pixels, local height pits (h - Blur40 < -0.18), AO minimum; things sticking out -> export height before and after and subtract to measure the lift
2. Back up before changing (*_vN_backup.sbs or _build_vN_backup/), bump the version
3. Change only the stage you located, rebuild everything, produce a comparison (vN-1 / vN / reference side by side)
4. Report with numbers: coverage, mean, p5/p95, relative height, clipped fraction
5. If the new version is worse overall, roll back the structure without hesitation and keep only what worked (lesson from Rocky_Ground_A v8)
6. Update the version log in the project doc

Order for hunting regular bright edges / straight lines: curvature brightening -> roughness edge polish -> 1 px cliffs in height -> 8-bit height to normal -> the outline itself is straight (multiplying by the original Tile Generator cuts every perturbation back to a straight line).

## 4. Mode C: break down a third-party .sbs
1. Open it in SD, use get_graph_info for nodes, frames, comments, outputs; walk the connections segment by segment by frame or x position
2. Render previews: sheet.jpg (BaseColor / Height / Normal / Roughness) into _preview_xxx/
3. Write <name>_节点流程.md next to the .sbs and also project_write it to claude/sd-<name>-breakdown.md. Fixed structure:
   - File info: path, graph name, node count, resolution, outputs, description of the result, dependencies (list custom nodes and remind that the dependencies folder must be copied too)
   - Core idea (quote the comments in the graph verbatim)
   - 1. Overall architecture (ASCII flow chart)
   - 2…N. One section per frame: node chain + key parameters
   - Numbered list of reusable techniques
   - Comparison with the project preferences: derived from final height or not, single shape + scatter or not; nodes that can be cleaned up (opacity 0, strength 0, pass-through nodes with unconnected inputs)
4. Fold new techniques from the breakdown into sd-node-techniques / sd-material-recipes (propose a skill update)

## 5. SD 16 / MCP pitfall cheat sheet

Enums (measured on SD 16)
- Blend blendingmode: 0 Copy / 1 Add / 2 Subtract / 3 Multiply / 4 AddSub (dest + 2×source - 1) / 5 Max / 6 Min / 7 Switch / 8 Divide / 9 Overlay / 10 Screen / 11 Soft Light; there is no 13. The MCP built-in docs saying 4 = Max are wrong; test every new Blend once with two Uniforms
- Slope Blur Grayscale 2 mode: 5 Max / 6 Min / 7 (or 0) Blur
- Tile Sampler: pattern 1 = Image Input; blending_mode 1 = Max (its own enum, different from Blend); color_parametrization_mode 0 Color / 1 Scale (height follows size) / 2 row / 3 column / 4 pattern index
- Shape pattern: 3 Paraboloid / 4 Bell
- Normal inversedy=False is DirectX

Value behaviour
- Histogram Scan: higher Position gives more white
- Levels levelinmid > 0.5 darkens (concave), < 0.5 brightens (convex)
- Tile Sampler mask_map_threshold: an instance is kept when mask > threshold, so a lower value keeps more; with no mask connected, any threshold > 0 filters out every instance
- The Tile Sampler color parameter does not lower pattern height -> add Levels after every layer to control height
- Tile Sampler rock diameter ≈ 0.48 × scale / grid; cell radius + position_random beyond about 1.1 cells cuts rocks at cell borders
- Blur / Blur HQ intensity is relative to size (at 2048 Blur 1.0 ≈ 16 px per side); for a fixed pixel width drive it with a $size function; atomic Blur below about 0.1 does nothing
- Atomic Warp intensity units are large, around 0.06; Directional Warp below 1 is barely visible, per-cell offsets use 300–9000
- Distance with a source input fills with falloff unless distance is large: 256 gives flat per-cell values, 20 leaves ramps that make a following Edge Detect draw ladder artifacts
- Distance units are much larger than pixels; Distance 40 at 2048 is 15× slower, 12 is enough
- Negative Bevel distance goes inward, -0.01 ≈ 10 px at 2048
- Edge Detect outputs black edges on white: Multiply it with the mask, do not Subtract
- When Height Blend top is always >= bottom, height_mask is all white; for additive layers add an ε to bottom
- A grayscale source blended onto a color destination does nothing: convert with Gradient Map first, or use the grayscale as opacity between two color Uniforms
- Transformation tiles by default: set $tiling 0 when scaling / stretching a single shape
- curvature_smooth_v2 radius has no effect; use curvature_smooth and blur the height first
- Shape Splatter v2 rock height does not scale with x/y_amount: height_scale ∝ 1/grid; mask_map is a hard threshold; density_map needs multiplier 1; amount is ignored in Poisson mode
- shape_splatter_mapper outputs 8-bit by default: set 16-bit before writing it into height
- Typical noise medians: Crystal ≈ 0.09, Dirt 3 ≈ 0.11, Moisture ≈ 0.53 — normalize before using as a mask; Creased leaves directional streaks, Dirt 3 contains letter-like patterns

Performance
- FX-map noises at large scale are very slow (BnW Spots 3 at 96 / 128 takes about 10 minutes, cost ∝ scale²): for fine grain use white_noise_fast -> Blur -> Levels
- Tile Sampler with >= 380² instances or a scale_map_input pushes the whole graph past 60 s
- The device VM has about 4 GB RAM and SD's Python has no numpy: preview at 1024, float32

MCP / Python
- MCP calls time out after about 60 s while SD keeps computing: run long work async with QTimer.singleShot, keep the callback on builtins so it is not garbage-collected, poll _preview/_done.txt; do not immediately repeat the call
- graph.compute() only guarantees nodes connected to an output: attach temporary output nodes for preview / export and delete them afterwards
- Never call disconnect() on output node connections (hangs or returns empty); a new connection replaces the old one; use the disconnect_nodes tool to break links
- A wrong port name makes MCP return only {}: check port names before wiring
- Read scripts containing non-ASCII text with open(..., encoding='utf-8'); Gradient Map keys: push gradient_key_rgba structs into an SDValueArray; enum parameters take SDValueInt
- An interrupted script leaves orphan nodes: delete non-output nodes not listed in nodes.json; unloadUserPackage temporary test packages
- 16-bit PNGs load in PIL as I;16, divide by 65535

## 6. Pre-delivery checklist
- [ ] Every output derives from H_final (state the source of each)
- [ ] Tileable (seam difference <= interior difference)
- [ ] Height does not clip (p99.5 < 1), no 8-bit steps (key nodes 16-bit)
- [ ] Oblique displacement / clay compared with the reference; confirm with an SD 3D view screenshot when needed
- [ ] BaseColor sRGB range sensible (darks >= 30–40), no red in PBR Validate
- [ ] Roughness range fits the material (rock 0.6–0.85, soil 0.85–0.96, water 0–0.05)
- [ ] No temporary outputs or orphan nodes; frames / comments updated
- [ ] Textures exported, project doc written
