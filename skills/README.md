# SD Material Skills

Three Agent Skills (written in Chinese) distilled from a personal Substance 3D Designer project
(`SD_Textures`: ~20 procedural PBR materials and node-flow breakdowns of third-party .sbs files).
They are meant to be used together with this repo's MCP server.

| Skill | Use it when | Contents |
|---|---|---|
| [`sd-material-workflow`](sd-material-workflow/SKILL.md) | building, iterating or breaking down a material | 3 modes (new / iterate on feedback / break down a .sbs), build-script framework (`_build/` with `h.py`, `cfg.py`, staged scripts, async preview/export), SD 16 + MCP pitfalls (enum values, sizes, timeouts), delivery checklist, doc template |
| [`sd-material-recipes`](sd-material-recipes/SKILL.md) | choosing an approach by material type | 9 categories: rocky ground / rubble (Tile Sampler layers, SDF Shape Splatter, Cells chain), dense aggregate, pebble beach, desert bedrock, fractured cliff, slate/stratified rock, tiles/mosaic/cobblestone, forest floor/moss/puddles, organic |
| [`sd-node-techniques`](sd-node-techniques/SKILL.md) | looking up a technique by production stage | single-shape generators, scattering & stacking, Flood Fill per-cell data, cutting planes, cracks & strata, sand/mud, moss, water, surface detail, normal/AO/curvature, BaseColor, Roughness, custom library nodes |

Core principles baked in: every map is derived from the final height; pebbles / shards / weeds are
built as a single heightmap first and then scattered with Tile Sampler (or Shape Splatter) inside a mask.

> File paths (`E:/Work/PersonalProject/SD_Textures/...`) and `claude/sd-*.md` doc references point to the
> author's own project. The techniques, parameters and pitfalls are general; replace the paths with your own.

## Install

**Claude Code (plugin marketplace)**
```
/plugin marketplace add yang1190/substance-designer-mcp
/plugin install sd-material-skills@substance-designer-mcp
```

**Claude Code (manual)**: copy the three folders into `~/.claude/skills/` (personal) or `<project>/.claude/skills/`.

**Claude.ai / Claude desktop**: upload the `.skill` files from [`packages/`](packages/) in *Settings > Capabilities > Skills*.

## Rebuild the packages
```
python tests/build_skill_packages.py
```
