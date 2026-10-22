---
name: sd-node-techniques
description: Substance Designer node technique library by production stage - single rock / pebble / leaf generators, Tile Sampler and Shape Splatter scattering, Flood Fill per-cell data, cutting planes and ridges, cracks and strata, sand, mud, moss, water, normal / AO, BaseColor, Roughness.
---

# SD Node Technique Library (by production stage)

The [Source] tag after each technique names where it comes from; for details project_read claude/sd-*.md or the *_节点流程.md (node flow) file next to the .sbs. Overall workflow: sd-material-workflow. Recipes by material: sd-material-recipes.

## 1 Single-shape generators (build one, then scatter)

Rocks
- Faceted round rock: Shape (Pattern 3) -> Perlin Directional Warp 50 -> skew and rotate -> Subtract 0.29 Cells 1 -> 3 Gradient Axial chained with Min -> Levels binary outline -> Edge Detect (roundness 5.86) Min with the rock [Desert_Rocky_Ground_01]
- Several fragments at once: Tile Generator 2×2 -> Flood Fill -> 3 Flood Fill to Gradient chained with Min, the last two using a Random Grayscale with a very narrow Levels (0.547–0.552) as opacity so only a few random pieces get an extra cut -> 3 Transformations to crop them out [Desert_Rocky_Ground_01]
- 3D block: Cube 3D (different orientation / size) × Shape Paraboloid (0.45) Min Polygon 2 (5–8 sides) -> Perlin Warp 0.06 [Rocky_Ground_A]
- Rounded bulging rock: Polygon 2 (6–10 sides, negative Curve) -> non-uniform stretch ($tiling 0) -> Perlin Warp -> 1–2 Gradient Axial half-planes with Min (straight break edges) -> silhouette S; shoulder Blur(S,30) × dome Blur(S,100) -> Min with a slanted plane -> slanted gradient for tilt [Beach_Rocky_Ground_B]
- Avoid repetition in large rocks: 6 dedicated silhouettes (4–8 sides, Curve 0.05–0.35, Scale 0.62, each rotated + stretched 1.0–1.45 + two straight cuts) [Beach_Rocky_Ground_C]
- Lightweight rock: Gradient × shape, Blend Darken (Min) with Perlin (keeps edges crisp) [80.lv Tom Jacobs]
- Pebble: circle Shape -> Multi Directional Warp 39 -> 3 FF to Gradient with Min -> Non-uniform Blur 5.9 to round; Crop into 4 [RiverPebbles]
- Rock slab: Cells 1 Highpass Overlay Polygon 2 -> two Slope Blur Max (Gaussian / Crystal as Effect) -> × gradient [DesertRock]
- Slate wedge: Polygon 2 -> Quad Transform -> rotate -> × Gradient Linear [SlateCliffRock]
- SDF rock: 3d_sdf_rock (facets 7–10, randomness 0.85–0.95) morphed with an ellipsoid 0.12–0.3 + simplex [StoneGroundA]

Other objects
- Glass shard: two Shapes in a Tile Sampler 7×7 -> Distance 256 -> Histogram Scan [ForestMirror glass_shard_generator]
- Fragment: 3–5 Gradation half-planes at different angles with Min -> Warp -> jagged edge -> chips -> narrow bevel × tilt gradient [TileFloor]
- Twig: thin Shape / Paraboloid -> Blur -> inflate -> Directional Noise distortion -> gradient Non-uniform Blur for the tip -> Tile Sampler of itself for branches -> Multi Dir Warp to bend [ForestMirror twig_generator]
- Leaf: Paraboloid Min a 45° rotated Pyramid -> flat top -> subtract midrib and V-shaped side veins (Tile Sampler 1×9, mirrored) -> Crystal warp on the edge; clusters with Splatter Circular [Grass_Ground_A, ForestMirror leaf]
- Moss clump: small leaf -> Tile Sampler radial cluster -> Shape Extrude for volume [RiverPebbles]; simple version Bell + Warp [TileFloor]
- Grass tuft: Splatter Circular (Thorn ×64 / ×40) -> Directional Warp to bend [Grass_Ground_A]

## 2 Scattering and stacking

Tile Sampler rules
- Next layer only fills the gaps: Mask Map = previous layer Histogram Scan -> Bevel -> invert (Bevel distance = spacing) [RiverPebbles], or the inverted Histogram Scan of the previous layer [Desert_Rocky_Ground_01]
- Size falloff: next layer Scale Map = inverted HBAO of the previous layer -> smaller rocks near big ones [Desert_Rocky_Ground_01]
- Clusters: Mask Map = HBAO -> Blur -> Levels (inverted) -> stones cluster only in hollows; Levels is easier to tune than Histogram Scan [ForestMirror, ForestPuddleGround]
- Scale Map and Color Map share one Moisture / Gaussian -> size and height vary in patches [RiverPebbles, SlateCliffRock]
- Bright-over-dark layering: color_random + Max blending, the random gray also sets height; then a morphological opening (Blur HQ -> Levels 0.5–0.54 -> multiply with the original mask) removes rocks squeezed into slivers [Beach_Rocky_Ground_C]
- color_parametrization_mode 1 (Scale) makes height follow size [Beach_Rocky_Ground_A]
- Compose: set absolute height per layer with Levels, then Max; or Height Blend per layer (0.7–0.85); add rocks onto the blurred ground, subtract a sink amount, Max with the current height (rocks follow terrain and bury their bases) [Rocky_Ground_A]
- Blur(ground) + object -> Max must be multiplied by the object silhouette, otherwise cracks get filled [TileFloor]
- Copy instead of adding a Tile Sampler when you can: Safe Transform offset / tile 2 / rotate existing results [ForestMirror]

Shape Splatter (v2 SDF and v1 patterns)
- Chained background_height + negative Height Offset (bury) + Rotation from Bg Slope + Mask from Bg Slope + Conform to Background; colors via Shape Splatter Blend Color on the same splatter data [Cobblestone_01]
- v2 SDF: height_scale ∝ 1/grid; density_map_multiplier 1; 3D rotation random 1 makes rocks stand upright [Rocky_Ground_A SDF]
- Density = ring (Blur(R, r) - tops) ∪ clustered noise; Mask excludes only tops -> small rocks lean against large rock sides [Rocky_Ground_A SDF]

Other
- Density sets size: dense points give small rocks, isolated points give large rocks (Cells points driven by a texture) [80.lv Tom Jacobs]
- Cells + DilationErosion360 dilation instead of multi-layer scattering [ConcreteRockField]
- Atlas Splitter + scan atlases -> Shape Splatter; Atlas Scatter stacks full PBR channels on a background [Cobblestone_01, RiverPebbles]

## 3 Per-cell data (the Flood Fill family)
- One Flood Fill, reused everywhere: To Random Grayscale (select cells, vary roughness), To Gradient (tilt / cutting planes), To Random Color (vector map), To BBox Size (big rocks tall, small rocks low), Flood Fill Mapper (per-cell texturing), To Position + Position to Color (deferred coloring)
- Distance (combine off) spreads each cell's value into the gaps, so no black lines appear and warps and sampling stay clean [RockCliff_A, tile-04]
- Different texture per cell: per-cell random value as the Directional Warp intensity map (intensity 300–9408) -> each cell samples a different part of the noise [tile-04, RiverPebbles, TileFloor]
- Per-cell direction: Flood Fill -> To Random Color -> Distance as the vector_map of Vector Warp [Cobblestone_01]
- Split cells into random new pieces: Distance (mask = Flood Fill to Gradient with random angle, source = Flood Fill to Random Grayscale, distance 256) -> each cell is re-cut along a random line into new flat-valued pieces -> Edge Detect = new cracks; do it twice with different seeds and Multiply the edges. Distance must be large enough to fill flat (distance 20 leaves falloff ramps and Edge Detect then draws ladder artifacts) [80.lv Rosen Kazlachev, verified]
- Random cell selection: Random Grayscale / Voronoi random color + a very narrow Levels or Histogram Select; expose position / range as graph parameters [tile-04, RockCliff_A]
- Per-rock ID matching the height one to one: silhouettes + a cloned Tile Sampler with the same seed + color random 1 [Desert_Rocky_Ground_01, Grass_Ground_A]
- Multi-layer IDs: each layer gets its own FF Random Grayscale, layered by which one is on top (H_n - H_n-1 > 0); a single Flood Fill on the merged mask paints touching rocks the same color [Rocky_Ground_A]
- Lines that are too thin let Flood Fill leak into giant cells; Edge Detect -> erode -> dilate closes gaps [TileFloor, ConcreteRockField]
- Per-rock UVs: FloodFillAlignedGradient ×2 -> UVConstruct -> UVMapper, texture follows each rock's orientation [ConcreteRockField]

## 4 Shaping
- Random facets: 3–6 Flood Fill to Gradient (angle variation 1, different seeds) chained with Min; wrap as a shape_cutter sub-graph (× bbox size -> Auto Levels -> subtract a Uniform -> Min with the original shape) [ForestMirror, Cobblestone_01]
- Ridges / prism tops: 3 FF to Gradient with Min × BBox (small blocks get lower ridges) [RockCliff_A]
- Cut the top only, keep the sides: facet Levels in 0.6 / out low 0.4 keeps tall side walls [Rocky_Ground_A v6]
- Per-cell tilt: FF to Gradient × per-cell random strength -> Levels output 1 -> 1 - tilt -> multiply; angle_input from large noise + small variation = neighbouring blocks lean the same way [Beach C, RockCliff_A]
- Block cross-section: inverted mask -> Distance -> small Blur -> 1 - (1 - x)³; at low resolution use Blur HQ + Levels instead of Distance [Beach B / C]
- Slope Blur uses: Source = Effect = inflate (0.001–0.05); self-fed Max = organic blobs; Min to erode edges 0.006–0.02 (> 0.1 gives concentric rings and comb artifacts); Min then Max = block faces; negative strength reverses [many]
- Warps: drive MDW with 64 px low-resolution noise to warp the outline only without fuzz; scale Warp down with size (large rock 0.35 -> gravel 0.025) [Rocky_Ground_A]
- Split edges / edge notches: Flood Fill the silhouette -> 2 random-direction FF to Gradient, binarize and multiply; silhouette edge band × Crystal Histogram Scan bites notches [Rocky_Ground_A v2]
- Shadows -> Invert -> Subtract = edges chipped as if cut by side light [Cobblestone_01]
- Center bulge with MVCenter; bevel with Bevel; round with Edge Detect roundness [ConcreteRockField etc.]
- Outline anti-aliasing: Blur HQ intensity = K / $size.x, replaced only inside the |H - blur(H)| edge mask [StoneGroundA]
- Floor fill: Blur 18 -> Levels + gravel -> Max with the original (prevents black spots in the 3D view); always put gravel on the floor [RockCliff_A]

## 5 Cracks / joints / strata
- Cracks following the rock: Tile Random -> Histogram Scan -> Distance (fill to flat cells) -> Crystal Warp 0.22 -> Edge Detect -> Blur 0.2 -> Directional Warp 46–72 driven by rock height -> Slope Blur Min with height as Effect -> Dilation to thicken -> Multiply 0.2 / 0.22 [DesertRock, Desert_Rocky_Ground_01]
- Tight, contracted cracks (ceramic tiles, crazing, sharp cuts) [80.lv Rosen Kazlachev 2025, prototyped in SD 16 at 1024]:
  1. Main shapes -> Flood Fill (or, cheaper, a tiny-scale Tile Generator with random grayscale -> Distance -> Edge Detect; Flood Fill is expensive)
  2. Randomize: Distance(mask = FF to Gradient, source = FF to Random Grayscale) twice, blended -> Edge Detect -> crack mask C (white pieces, black lines)
  3. Classic step: Slope Blur of C with Perlin / Clouds as Effect (optional warp before)
  4. Contraction: a second Slope Blur on that result, Effect = Invert(Blur HQ(C, 0.33)), intensity 0.02 -> pieces shrink and get a thin sharp top edge. Mode Blur (7) and Min (6) gave nearly the same result. 0.02 is deliberately exaggerated: at 1024 it widened crack coverage from 9% to 24%; use about 0.005–0.01 for hairline cracks
  5. Per-piece variation from the final cracks: Invert -> Histogram Scan (tighten, otherwise dotted lines let pieces merge) -> Flood Fill -> FF to Gradient (random angle) + FF to Random Grayscale
  6. Combine: base shapes -> Overlay random grayscale -> Overlay random slopes -> Subtract inverted cracks
  - Not covered by the method: width variation, branching, chipping, color / roughness; add them with the techniques above (Edge Detect on random values, Slope Blur Min chipping, curvature masks)
- Fine cracks: Perlin -> Perlin Warp -> Crystal Warp 0.012 (jagged) -> Histogram Select range 0.008 thin lines -> × Perlin segment mask [Beach B]
- Straight joints: Tile Sampler thin Pyramids in 3 directions × coarse / fine, rotation map from Clouds (0.039) [RockCliff_A]
- Engrave only real block borders: Edge Detect on per-block random values, not on joint lines (avoids worm-like double lines) [RockCliff_A]
- Strata: Quantize 8 steps for terraces + 51 steps for fine layers, Shadows mask keeps them on lit faces [DesertRock]; large-scale fixed-angle Tile Sampler [SlateCliffRock]
- Cliff hard lines: dense fracture fragments (Polygon × Gradient Axial) on a mid-gray 0.5 background, two Tile Samplers Min -> Highpass, added only inside large rocks; sparse placement looks like plates glued on [Rocky_Ground_A v5]
- Wind erosion: the same Clouds Directional-Warped 37 by Moisture at 3 angles, combined -> Highpass [Desert_Rocky_Ground_01]

## 6 Sand / mud / accumulation
- Sand and mud fill: inverted rock height -> Non-uniform Blur (anisotropy / asymmetry for wind direction) -> Slope Blur sliding down -> fill low areas with Max [80.lv, DesertRock]
- Sand piled at rock bases: rock height Blur HQ 9 -> Levels 0–0.34 × Clouds -> Max with sand -> inflate Slope Blur 0.02 [Beach A]; StoneGroundA: rock part above ground -> Non-uniform Blur 14 -> Levels × 0.035 -> Slope Blur 3
- Sand pushed by rocks: blurred rock height drives the sand Directional Warp 25 [Desert_Rocky_Ground_01]
- Rocks buried in mud: Height Blend (top mud, bottom rock, position 0.14) -> the mask output is the mud mask [RiverPebbles]
- Directional drag marks in mud: Multi Dir Warp + a huge Slope Blur Min (86, self as Effect); everything stacked with low-strength AddSub [Cobblestone_01]
- Sand accumulation: SandAccumulationEffect (radius 12, intensity 6.5, noise multiplier), sand color = whole-image Blur HQ 32 [ConcreteRockField]
- Dust in hollows: MG Dust (AO + normal) [DesertRock, tile-04]

## 7 Moss / foliage
- Moss mask = Moisture Histogram Scan × Bevel of selected stone tops + HBAO hollows - inverted RT AO; MG Metal Edge Wear finds hollows for extra moss [RiverPebbles]
- Growth along flow: FlowMap Generator -> Vector Morph 0.004 [ForestMirror]
- Moss is a thin layer on the crack floor: base it on the original height (unblurred) + carpet thickness 0.004–0.011, combine with Max; edge = binary carpet Blur HQ 2.5 ramp + Perlin noise AddSub 0.4 -> Levels 0.40–0.52 narrow threshold + scattered specks outside [TileFloor v7]
- One mask drives moss height, BaseColor, Roughness and Metallic together [TileFloor, ForestMirror]
- Moss color: dark olive (42,46,28) -> (110,106,64); never a translucent green tint over the base material [TileFloor]
- Thin leaves: stamp with a Color Tile Sampler, build normal / AO / height by hand, Rotation Random 0; replace normals per region [ForestMirror]

## 8 Water
- Water Level node: water level as a graph parameter; noise on the mask varies the level spatially; sludge, edges wetness, depth blur [RiverPebbles, Cobblestone_01]
- Manual water: Uniform gray = water level, Height Blend (contrast 1) settings fixed; shore Distance 55.9 -> Slope Blur gradient; muddy water color Copy 0.42–0.57, HSL darker with depth; roughness 0 [ForestMirror]
- Underwater stones: base color Blur 0.1 + HSL darker and warmer, shown through with water area × height as opacity [RiverPebbles]

## 9 Surface detail
- Add detail without changing big forms: Highpass, then low-strength AddSub (0.01–0.05); many light layers [80.lv, Cobblestone_01]
- Crumpled-foil facets: Crystal 1 (24 / 40 / 64) high-passed AddSub ±0.02–0.06, rocks only [Beach B / C]
- Detail that flows with the form: drive Slope Blur / Directional Warp / Vector Warp with a blurred copy of the rock itself [80.lv, DesertRock]
- Restore edges softened by Slope Blur with a curvature mask [80.lv]
- Pores: small dot Tile Sampler Subtract 0.04; BnW Spots Histogram Scan Subtract [Beach B]
- Make non-tileable grunges tile first with Make It Tile Patch / Photo [tile-04, Cobblestone_01]
- Reuse noise: keep a noise library, offset / rotate with Transform instead of new noise nodes; 3 scales are enough [ForestMirror]

## 10 Normal / AO / curvature / height output
- Height to Normal World Units (200–300 cm / 20–60 cm); with large macro relief the depth cannot be too small, or rocks end up only a few cm tall [Rocky_Ground_A v4]
- Per-region normal replacement: make a global normal from the final height, then swap in dedicated normals for foliage / glass / stones by mask; visible-part mask = Blend Divide (layer height / final height) -> Histogram Scan [ForestMirror]
- Detail normal: RT Bent Normal; Flat Normal over sand [DesertRock]
- AO: HBAO in world units; multiply HBAOs of several depths; BaseColor uses a local HBAO on the high-passed height [many]
- Two-scale curvature: wide = height blurred by 4 -> Normal -> Curvature Smooth (ridges), fine = original height (sharp edges); edge = wide high × fine high; fine curvature alone treats rounded tops as edges [Rocky_Ground_A SDF v4]
- Curvature thresholds depend on Normal strength: re-tune concave / convex thresholds after changing it [Rock_Cliff_A]
- Height output can go through Height Map Frequencies Mapper to rebalance low / high frequencies [Desert_Rocky_Ground_01]

## 11 BaseColor
- Order: palette (per-cell ID lookup) -> mottling texture Overlay -> mineral grains (about 5% coverage) -> rust / stains -> curvature volume Overlay -> edge wear highlights -> crevice dirt -> dust on up-facing surfaces -> local AO multiply (map AO to 0.5–1 first, then × 0.3) -> Sharpen 0.1 -> PBR Albedo Safe Color
- Palette first: k-means on reference chromaticity; give cells different color sets (several Gradients Copied in sequence through random masks) [Desert_Rocky_Ground_01, Rocky_Ground_A v7]
- Color noise that follows the form: Fractal Sum Vector-Warped by the Gradient of the height [DesertRock]
- Get_Slope separates flat / sloped colors; Shadows desaturates the shadow side [DesertRock, SlateCliffRock]
- Curvature as the main color source: Curvature Smooth -> several Gradients; narrow Histogram Select picks iso-lines for thin veins; offset masks with Transformation before use so color does not match form too rigidly [SlateCliffRock]
- Quartz veins / dark hairline cracks: Perlin -> Warp -> very narrow Histogram Select -> × segment mask, only inside large / medium rocks [Rocky_Ground_A v7]
- Convert grayscale to color with Gradient Map before blending onto color; Copying neutral gray grain at too high coverage washes colors out [Grass_Ground_A, Rocky_Ground_A SDF]
- No large low-opacity washes in color masks (they become a tint over everything) [TileFloor]
- Photo-sampled Gradient keys can be copied from mirror.sbs / Cobblestone_01 [ForestPuddleGround]

## 12 Roughness
- Roughness = Albedo grayscale -> inverse Levels mapping (e.g. 0.1–0.5 -> 0.96–0.70) + the same patterns as Overlay + convex edges -0.08; the most direct and consistent with color [Rocky_Ground_A v4, SlateCliffRock]
- Solid base + noise overlay: base value and amount of detail controlled separately; one Uniform per layer Copied through the layer mask [ForestMirror]
- Typical values: rock 0.62–0.84, gravel 0.76–0.88, soil 0.88–0.96, sand 0.78 (wet 0.55), moss 0.62–0.88, glazed tile 0.47, polished 0.30, water 0
- Per-cell grunge: grunge Directional-Warped 156 by the per-rock random value so every rock samples a different spot [Desert_Rocky_Ground_01]
- Lower roughness at sand sparkle points [DesertRock]

## 13 Custom library nodes
- Tom Jacobs (CustomLibrary, verified on SD 16): Flood Fills (rocks / bbox / randomgray / randomgradient), Shift Rocks (RandomMASK takes the raw Cells 4), Edge Variation (edge_width 2.16, roundness 10.16), Add To Ground, Push Edges, Rock Sharp / Shelter 001, Simple Outputs (preview only); get_library_nodes('tom jacobs'); create_instance_node(resource_url='FloodFills')
- MV series (ConcreteRockField/dependencies): CellFieldPixelProcessorII, DilationErosion360, StoneBlocks, PostSelectCells, RemoveEdges, MVCenter, MultiChannelDirectionWarp, SandAccumulationEffect, SimpleOutputs
- ForestMirror dependencies: uniform_additive_blending (height add with built-in auto levels), material_tile_sampler (multi-channel in sync), position_to_color, Bruno_FlowMap_Generator
- Tutorial nodes: Get_Slope, nondirectional_warp, filter_dilation_or_erosion [DesertRock Tutorial nodes]
- Built-in substitutes: uniform_additive_blending ≈ Auto Levels then Add; Get_Slope ≈ the G channel of the normal for up-facing surfaces
