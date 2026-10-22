---
name: sd-material-recipes
description: Pick a Substance Designer recipe by material type - rocky ground, pebble beach, desert, fractured cliff, slate strata, tiles / mosaic / cobblestone, forest floor with moss and puddles, organic flesh - with pipelines, starting parameters and reference files.
---

# SD Material Recipes (by material category)

Find the recipe by category first, then read the reference files for details. Workflow, script framework and pitfalls are in sd-material-workflow; individual techniques are in sd-node-techniques.

Where the references live:
- Project docs: project_read claude/sd-*.md (written below as [doc:name])
- Local breakdowns: the *_节点流程.md (node flow) files next to each .sbs under E:/Work/PersonalProject/SD_Textures (written below as [md:path])

## Category index

| Category | Keywords | Preferred approach | Best references |
|---|---|---|---|
| 1 Rocky ground | rocky ground, rubble, gravel, mountain scree | 1A single shapes + layered Tile Sampler, or 1B SDF Shape Splatter | Desert_Rocky_Ground_01, StoneGroundA, Rocky_Ground_A |
| 2 Dense rubble / aggregate | concrete aggregate, rubble field, gravel bed | Cells + dilation | ConcreteRockField |
| 3 Pebble / river / beach rocks | pebbles, river bed, beach | 6-layer Tile Sampler + mud + water | RiverPebbles, Beach_Rocky_Ground_A/B/C |
| 4 Desert / sand / bedrock | desert, bedrock, dune, sand ripples | slab shapes + Quantize strata + sand | DesertRock_Tutorial |
| 5 Fractured cliff | cliff, fractured rock, joints | joint-based blocks + Flood Fill ridges | RockCliff_A |
| 6 Stratified rock / slate | slate, stratified, shale | single wedge + large-scale fixed-angle Tile Sampler | SlateCliffRock 14 |
| 7 Tiles / mosaic / brick / cobblestone | tile, mosaic, brick, cobblestone, flagstone, broken stone tiles | regular grid + per-cell random value + grout Height Blend | tile-04, HavanaStoneFloor, TileFloor, Cobblestone_01, Broken_Tiles |
| 8 Forest floor / foliage / moss / puddles | forest floor, moss, leaves, puddle, grass | one row per channel + layer masks + Position Map | ForestMirror, ForestPuddleGround, Grass_Ground_A |
| 9 Organic / flesh | guts, flesh, organic | noise + warps + self-fed Slope Blur | BloodyGuts |

---

## 1 Rocky ground

### 1A Single shapes + layered Tile Sampler (the project's standard approach)
References: [md:Desert_Rocky_Ground_01/Desert_Rocky_Ground_01_节点流程.md], [doc:sd-rocky-ground-a], [doc:sd-beach-rocky-ground-c]
```
4–6 single rocks -> L1 large rocks Tile Sampler -> L2 -> L3 -> L4 (each layer fills only the gaps)
 -> rock surface detail -> Height Blend with ground -> scatter fine gravel on the ground again -> H_final
```
- Single rock: Shape / Polygon 2 / Cube 3D base -> Warp to break the outline -> 3 Gradient Axial or Flood Fill to Gradient chained with Min for facets -> Edge Detect with roundness to bevel
- Starting layer table (Desert_Rocky_Ground_01): 6×6 (mask random 0.81, very sparse) -> 20×20 -> 30×30 -> 125×125
- Next layer Scale Map = inverted HBAO of the previous layer (smaller rocks close to big ones); Mask Map = inverted Histogram Scan of the previous layer (gaps only)
- Compose: Height Blend per layer (position 0.7–0.85); lower small rocks first with a Min against a Histogram Range. Or set absolute heights with Levels per layer, then Max
- Rocky_Ground_A layer table (grid / scale / height): A 8 / 1.37 / 0.60, B 22 / 1.35 / 0.38, C 38 / 1.75 / 0.30, D 56 / 1.7 / 0.19, E 100 / 1.8 / 0.11; place rocks on the blurred ground H_glow, subtract the sink amount, Max with the current height
- Density: large rocks = Clouds Histogram Scan; medium / small = max(halo around large rocks (Blur), clustered noise) × (1 - dilated footprint of the previous layer)

### 1B SDF Shape Splatter v2 (real volume, rocks on rocks)
References: [doc:sd-rocky-ground-a-sdf], [doc:sd-stone-ground-a-mountain-rubble] (template StoneGroundA/_build/)
- Each pass's background_height = composite of all previous passes; height_offset_from_background 1, slope_rotation 1, smooth_background_slope 0.4 -> new rocks land on older ones and follow the slope
- SDF: rock (facets 7–10, randomness 0.85–0.95) morphed with a little ellipsoid + simplex; height_scale = 0.96 × hd × 9 / grid
- Density: large rocks only on the terrain crest band (t_band 0.5–0.85) × clustered noise; later passes = ring around the previous pass (Blur(R) - tops) ∪ noise; gravel = HBAO crevices × near-rock mask
- Required: outline anti-aliasing (Blur HQ intensity = K / $size.x, replaced only inside the |H - blur(H)| edge mask)
- Extra: two-scale curvature edge chipping written into height (-0.005)

### 1C Tom Jacobs Cells chain (fast full-coverage rubble)
References: [doc:sd-80lv-rocky-ground-tom-jacobs], [doc:sd-customlibrary-tom-jacobs-nodes]
```
Cells 4 (scale 7) -> Edge Detect -> Flood Fills.rocks -> Shift Rocks.Rocks
raw Cells 4 -> Shift Rocks.RandomMASK; Cells 4 -> Edge Variation.heightmask
Shift Rocks -> Add To Ground(Top, Bottom = ground) -> Push Edges -> maps
```
- Downside: Edge Detect seam lines leave thin ridges around rocks and rocks look like mesas (StoneGroundA v1 switched to SDF because of this)

### Common problems
- Rocks look buried: macro relief / stacking lift ate the relative height -> measure H - Blur(H), reduce sinking, keep taller side walls (facet Levels in 0.6 / out low 0.4)
- Gravel lines up in a honeycomb along ground undulations: ground mid frequencies too dense -> smooth the ground, restrict gravel density to the vicinity of rocks
- Gravel looks like coins / steel balls: Tile Sampler color does not lower height -> Levels per layer; do not inflate small objects with Slope Blur (they turn into plateaus)
- Rocks look too much like the prototype: use 6 dedicated silhouettes for large rocks (different side counts, non-uniform stretch, two straight Gradient Axial cuts)

## 2 Dense rubble / aggregate (ConcreteRockField)
Reference: [md:ConcreteRockField/ConcreteRockField_节点流程.md] (many MV custom nodes in dependencies/)
- Core: a cell map with a random gray per cell -> DilationErosion360 (distance 15, 200 steps), bright cells grow over dark cells -> natural layering and half-buried stones
- Edge Detect -> erode 2 -> dilate 2 to close gaps -> StoneBlocks (Flatness 0.52) -> RemoveEdges -> MVCenter center bulge -> PostSelectCells samples the dilation value / noise per cell for per-stone height
- MultiChannelDirectionWarp warps height and 3 masks with the same angle / strength (color always lines up)
- SandAccumulationEffect: small radius smooths edges, large radius + noise multiplier accumulates sand and outputs a sand mask; sand color = whole-image Blur HQ 32
- Built-in alternative: Tile Sampler color_random + Max blending, the brighter stone ends up on top and also sets the height (used in Beach_Rocky_Ground_C)

## 3 Pebble / river / beach rocks
References: [md:RiverPebbles/SBS/RiverPebbles_节点流程.md], [doc:sd-beach-rocky-ground-a], [doc:sd-beach-rocky-ground-b]
- Single pebble: circle Shape -> Perlin-driven Multi Directional Warp 39 -> 3 Flood Fill to Gradient with Min -> Non-uniform Blur 5.9 to round it -> Crop into 4 pebbles
- 6 Tile Sampler layers: 8² / 14² / 22² / 40² / 60² / 80², Mask Map = previous layer Histogram Scan -> Bevel -> invert (Bevel distance = spacing between stones); Scale Map and Color Map share one Moisture noise (patchy distribution)
- Mud: Height Blend (top mud, bottom pebbles, position 0.14) -> pebbles half buried, the mask output is the mud mask
- Water: pack with PBR Base Material -> Water Level (water level exposed as a graph parameter); underwater stones = original base color blurred + darkened with HSL, shown through with water area × height as opacity
- Beach: sand piles at rock bases = Blur HQ 9(rocks) -> Levels 0–0.34 × Clouds -> Max with the sand surface; gravel on sand is Added on top of the sand (not cut into it); soften the contact band by Copying the blurred height at 0.8
- Lay a blurred version over a hard one with Min, not Copy (Copy leaves a skirt around the outline)

## 4 Desert / sand / bedrock
References: [md:Daniel Thiger - Tutorial Desert Bedrock（Substance Designer 沙漠基岩制作教程）/DesertRock_Tutorial_节点流程.md], [doc:sd-desert-bedrock-tutorial-breakdown]
```
slab shape (Cells + Polygon -> two Slope Blur Max) -> Tile Sampler 4×4 -> Directional Warp
 -> Quantize 8 steps (terraces) -> cracks -> Quantize 51 steps fine strata (lit faces only)
 -> sand (low-area threshold + Non-uniform Blur for wind direction) -> ripples -> pebbles (MG Dust mask) -> soften sand
```
- Ripples: two Gaussian Tile Samplers Directional-Warping each other + Curve; Vector Warp with the Gradient of the sand shape (strength -0.01) bends ripples along the sand pockets
- Pebbles push the sand away: Non-uniform Blur with the pebble mask as Effect, then Add the pebbles
- Sand sparkles: White Noise plus copies rotated ±90° RGBA-merged into a random normal, only on sparse points and sand, with roughness lowered there
- Rock detail normal from RT Bent Normal; sand areas switch to a flat normal
- Desert rocky ground (red-brown sand + multi-size gravel): use 1A plus the Desert_Rocky_Ground_01 sand: rock height drives the sand's Directional Warp (sand pushed away by rocks)

## 5 Fractured cliff
References: [md:Rocks_A/RockCliff_A_节点流程.md], [doc:sd-rockcliff-a-whitemodel], [doc:sd-rock-cliff-a], [doc:sd-rocks-a-fractured-cliff]
```
1 Joints: 6 Tile Samplers with thin Pyramids (3 directions × coarse/fine) + Voronoi large fissures + local subdivision -> Flood Fill (~1400 blocks)
2 Plates: random height + tilt (angle_input from large noise, angle variation 0.15) + 3-way ridges (3 FF to Gradient with Min) × BBox -> engrave real block borders -> hairline cracks -> lift to 0.5–0.98 × rock-mass zones
3 Rubble: blurred rock mass as fill surface + 5-scale Voronoi fragments, only outside the rock mass
4 Compose: Crystal chiselling -> two Warps -> Slope Blur Min (<= 0.02) -> Max rubble -> micro detail -> Blur 18 + Max floor
```
- Joint rotation_map from Clouds (multiplier 0.039) -> joints drift slowly; zones are decided per whole block (Flood Fill to Grayscale + very narrow threshold)
- Pitfall: Distance / shoulder effects based on joint lines create pairs of worm-like ridges on both sides of dead-end lines -> use only Edge Detect on per-block random values (real borders)
- Pitfall: Slope Blur > 0.02 on tilted rock faces drags out parallel streaks; large Max fills need rubble on top, otherwise they read as smooth empty patches
- Color reference: mean sRGB (138,123,110); deep cracks warm and saturated (69,57,48), ridges whitish (196,182,167)
- To match the preferences: replace rubble with a single angular fragment -> Tile Sampler (Mask Map = inverted rock mass)

## 6 Stratified rock / slate
References: [doc:sd-slatecliffrock-14-breakdown], [doc:sd-stratified-rock-material]
- Single wedge: Polygon 2 -> Quad Transform -> rotate 46° -> × Gradient Linear
- Tile Sampler 13×13, scale 36 (much larger than a cell, heavy overlap), rotation fixed at 0.857 with random 0.03 -> strata; Scale / Color / Distribution Map share one Gaussian Noise
- Subtract a stretched, sheared Crystal -> long parallel grooves; chained Directional Warps bend the strata; Slope Blur Min followed by Max gives block faces
- Two scales of Cells 3 -> Edge Detect -> Bevel -> Slope Blur for broken plates, added locally through a Clouds mask
- Color mostly from final curvature; rust veins = very narrow Histogram Select on curvature (range ~0.04); Roughness = inverted BaseColor with Levels
- Simple stratified rock: Tile Sampler (Gradation, 3×9, rotation 0.95) + directional motion blur to shorten plate ends

## 7 Tiles / mosaic / brick / cobblestone
References: [md:TileSet/tile-04_节点流程.md], [doc:sd-havana-stone-floor], [doc:sd-tilefloor-broken-inlay], [doc:sd-cobblestone-01-breakdown], [md:Artstation - Broken Tiles Tutorial - VOL 01/Broken_Tiles_Tutorial/Broken_Tiles_节点流程.md], [doc:sd-broken-tiles-tutorial-breakdown]
```
pattern shapes (Tile Generator grid / Splatter Circular rings / 45° rotated diamonds) -> Multi Switch(Pattern)
 -> per-cell data (Flood Fill -> Random Color -> Distance -> R channel = #408)
 -> tile body (Bevel -> Slope Blur edge nibbling -> per-cell height / tilt / per-cell noise / cracks / damage / chipping)
 -> grout (derived from the tile shape) -> Height Blend(position 0.4) -> H_final
```
- Per-cell noise: Directional Warp intensity 500–9408 with #408 as the intensity map -> each tile samples a different part of the noise
- Parametric tile selection: expose Histogram Select position / range as graph parameters (cracks, damage, chipping, dust)
- One Pattern parameter switches height and colors together (two Multi Switch nodes)
- Irregular tile outline (Havana v8): add noise to the Bevel linear distance of the Tile Generator, then threshold; do not multiply by the original Tile Generator (it cuts back to straight lines)
- Grout height follows neighbouring tiles (weighted average, lower tiles dominate); add grain back after blurring the grout band, otherwise it is a smooth rubber strip
- Cobblestone (Cobblestone_01): Tile Random -> Distance fill -> Cutting Planes (5 FF to Gradient with Min) -> inverted Shadows for cut edges -> 20+ low-strength detail layers; Shape Splatter for gravel / twigs in the gaps, Atlas Scatter for moss and leaves
- Cracked glaze / crazing on tiles: use the tight contracted-crack chain in sd-node-techniques section 5 (Distance-randomized pieces -> second Slope Blur with inverted blurred cracks as Effect -> per-piece tilt from the final cracks), driven per tile by #408 so only selected tiles crack
- Worn / broken stone tiles (Broken_Tiles, octagon + diamond inserts, 463 nodes):
  ```
  octagon = square × 45° rotated square -> Tile Sampler 4×4 (+ slightly larger sampler inverted, Max = diamond inserts)
   -> per-tile data: Flood Fill -> Random Grayscale ×2 + Gradient -> Distance 10000 (mask = Histogram Scan Position 1)
   -> edge damage (per-tile corner roundness + 4 Slope Blur Min passes) - engraved ornaments (aligned Tile Sampler) × surface wear
   - cracks on selected tiles (+ crack pieces tilted) × per-tile tilt, Copy 0.25 per-tile height
   -> Height Blend cement (0.55) -> Height Blend pebbles Shape Splatter (0.31) -> Normal 30 / HBAO
  ```
  - Per-tile variety everywhere comes from one random map driving Directional / Non-uniform Directional Warp (intensity and angle)
  - BaseColor: two tile color sets picked per tile by a Tile Sampler with the tile grid's parameters and a noise mask_map; MG Metal Edge Wear lightens chipped edges and cracks; MG Dirt
  - Atlas_Scattering graph: twigs -> leaves -> tiny leaves as chained Atlas Scatter on top of the material, collected in low areas
- Broken inlay (TileFloor): moss is a thin layer on the crack floor (Max, not AddSub); break its edge with a blurred ramp + noise AddSub + narrow threshold
- Exposed parameters, after Havana: Tile_Tilt 0.06, Tile_Height_Variation 0.03, Mud_Overflow, Polish_Amount, Crack_Amount, Edge_Damage, Dirt_Amount

## 8 Forest floor / foliage / moss / puddles
References: [md:JRO_Nature/JRO_ForestMirror/mirror_节点流程.md], [doc:sd-forest-puddle-ground], [doc:sd-grass-ground-a]
- Layout: a noise library on the far left, reused everywhere; one row per channel (Height / Position / Roughness / Metallic / BaseColor); each new layer gets one Blend per row in the same column, all driven by the same layer mask
- Mud: three versions of BnW Spots 2, each with a Slope Blur where Source = Effect (0.05 / 0.019 / 0.004, inflate)
- Stone layers: L1 Cells stones (no intersections) -> L2–L4 Tile Sampler (7² -> 10² -> 17² -> 33²), mask = previous layer HBAO -> Blur -> Levels, inverted; each stone goes through shape_cutter; Uniform Additive Blending, or Auto Levels then Add
- Deferred coloring with a Position Map: accumulate Flood Fill to Position per layer, then one Position to Color at the end
- Twigs / glass shards / leaf clusters: sub-graph generators + Tile Sampler; if Safe Transform copies are enough, skip the extra Tile Sampler
- Thin leaves: stamp with a Color Tile Sampler and build normal / AO / height by hand; replace normals per region
- Moss: inverted HBAO + FlowMap Vector Morph to grow along the flow; moss mask = Moisture × stone tops + AO crevices
- Water: a Uniform gray sets the water level (Height Blend settings stay fixed); shore Distance gradient + muddy water color + darkening with depth; water roughness 0
- ForestPuddleGround numbers: BaseColor median ≈ 0.26, AO median ≈ 0.8; palettes can be copied straight from the Gradient keys in mirror.sbs
- Grass ground (Grass_Ground_A): Blur HQ 6 the ground under leaves first; per-leaf ID / detail through a cloned Tile Sampler (copy every parameter including $randomseed)

## 9 Organic / flesh
Reference: [doc:sd-bloody-guts-breakdown]
- One height trunk: Perlin soft-light stacking -> Directional Warp -> self-fed Slope Blur (Max, Effect = own Blur HQ) about 15 times for blobby masses
- Blur HQ -> Slope Blur -> Blur HQ sandwich; stack mostly with Soft Light, Multiply for creases, Screen for raised detail, Subtract for dents (0.03–0.5)
- Veins: Cells 1 -> Slope Blur Max -> Non-directional Warp -> Directional Warp driven by the trunk -> Invert -> Screen 0.04 (two scales)
- Color: flesh Gradient + bluish veins (0.12,0.21,0.26); blood with an alpha Gradient Map using curvature as opacity, only in hollows
- Roughness: a strong normal (60) gives a two-way curvature Screen -> interpolate 0.14 to 0.55; Subtract for wet blood areas

---

## Decision rules
- Rocks scattered sparsely on ground -> 1A; real volume, rocks on rocks, following slopes -> 1B; rocks covering everything and pressing together -> 2
- Vertical cliff with blocky fractures -> 5; diagonal layering -> 6; horizontal terraces -> Quantize from 4
- Regular geometry -> 7 (grid + masks, no Tile Sampler)
- Mixed surfaces (mud + stones + foliage + water) -> the row layout + Position Map from 8
- When unsure, build clay samples (1024) of one or two approaches for the user to compare
