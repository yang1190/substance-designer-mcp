---
name: sd-node-techniques
description: Substance Designer 节点技巧库，按制作环节查：单体石头/卵石/叶片、Tile Sampler 与 Shape Splatter 散布、Flood Fill 逐块数据、切面屋脊、裂纹层理、沙泥苔藓水、法线 AO、BaseColor、Roughness。
---

# SD 节点技巧库（按制作环节）

每条技巧后的【】是出处，细节用 project_read claude/sd-*.md 或 sbs 旁的 *_节点流程.md 查。整体流程见 sd-material-workflow，按材质选配方见 sd-material-recipes。

## 1 单体生成器（先做单体，再散布）

石头
- 带切面圆石：Shape(Pattern 3) -> Perlin Directional Warp 50 -> 斜切旋转 -> Subtract 0.29 Cells 1 -> 3 个 Gradient Axial 连续 Min -> Levels 二值轮廓 -> Edge Detect（圆角 5.86）与石头 Min【Desert_Rocky_Ground_01】
- 多块碎石：Tile Generator 2×2 -> Flood Fill -> 3 个 Flood Fill to Gradient 依次 Min，后两个用 Random Grayscale 极窄 Levels（0.547–0.552）作 opacity，只给随机几块多切一刀 -> 3 个 Transformation 裁出【Desert_Rocky_Ground_01】
- 3D 体块：Cube 3D（不同 orientation / size）× Shape Paraboloid（0.45）Min Polygon 2（5–8 边）-> Perlin Warp 0.06【Rocky_Ground_A】
- 圆润鼓边石：Polygon 2（6–10 边，Curve 为负）-> 非等比拉伸（$tiling 0）-> Perlin Warp -> 1–2 个 Gradient Axial 半平面 Min（直破裂边）-> 剪影 S；肩部 Blur(S,30) × 穹顶 Blur(S,100) -> 斜平面 Min -> 斜向渐变倾斜【Beach_Rocky_Ground_B】
- 大石防重复：6 个专用剪影（4–8 边，Curve 0.05–0.35，Scale 0.62，各自旋转 + 拉伸 1.0–1.45 + 两条直切边）【Beach_Rocky_Ground_C】
- 轻量单石：Gradient × 形状 Blend Darken(Min) Perlin（边缘保持锐利）【80.lv Tom Jacobs】
- 卵石：Shape 圆 -> Multi Directional Warp 39 -> 3 个 FF to Gradient Min -> Non-uniform Blur 5.9 磨圆；Crop 拆 4 块【RiverPebbles】
- 岩板：Cells 1 Highpass Overlay Polygon 2 -> 两次 Slope Blur Max（Gaussian / Crystal 作 Effect）-> × 渐变【DesertRock】
- 楔形板岩：Polygon 2 -> Quad Transform -> 旋转 -> × Gradient Linear【SlateCliffRock】
- SDF 石：3d_sdf_rock（facets 7–10，randomness 0.85–0.95）morph 椭球 0.12–0.3 + simplex【StoneGroundA】

其他物件
- 碎玻璃：两种 Shape Tile Sampler 7×7 -> Distance 256 -> Histogram Scan【ForestMirror glass_shard_generator】
- 碎片：3–5 张不同角度 Gradation 半平面 Min -> Warp -> 锯齿 -> 崩口 -> 窄倒角 × 倾斜渐变【TileFloor】
- 树枝：细长 Shape / Paraboloid -> Blur -> 充气 -> Directional Noise 扭曲 -> 渐变 Non-uniform Blur 做尖 -> 自身 Tile Sampler 分叉 -> Multi Dir Warp 弯曲【ForestMirror twig_generator】
- 叶片：Paraboloid Min 旋转 45° Pyramid -> 平顶 -> 减中脉和 V 形侧脉（Tile Sampler 1×9 镜像）-> Crystal 扭曲边；叶簇 Splatter Circular【Grass_Ground_A、ForestMirror leaf】
- 苔藓团：小叶 -> Tile Sampler 放射成簇 -> Shape Extrude 立体化【RiverPebbles】；简版 Bell + Warp【TileFloor】
- 草丛：Splatter Circular（Thorn ×64 / ×40）-> Directional Warp 弯曲【Grass_Ground_A】

## 2 散布与堆叠

Tile Sampler 规则
- 下一层只填上一层的空隙：Mask Map = 上一层 Histogram Scan -> Bevel -> 反相（Bevel 距离 = 石间距）【RiverPebbles】，或上一层反相 Histogram Scan【Desert_Rocky_Ground_01】
- 大小过渡：下一层 Scale Map = 上一层 HBAO 反相 -> 靠近大石的更小【Desert_Rocky_Ground_01】
- 成簇：Mask Map = HBAO -> Blur -> Levels（invert）-> 石头只在凹处成簇；Levels 比 Histogram Scan 好调【ForestMirror、ForestPuddleGround】
- Scale Map 与 Color Map 共用一张 Moisture / Gaussian -> 大小和高度成片分布【RiverPebbles、SlateCliffRock】
- 亮压暗层叠：color_random + Max 混合，随机灰度同时决定高度；再做形态学开运算（Blur HQ -> Levels 0.5–0.54 -> 乘原遮罩）去掉被压成月牙的石头【Beach_Rocky_Ground_C】
- color_parametrization_mode 1（Scale）让高度随大小变化【Beach_Rocky_Ground_A】
- 合成：每层 Levels 定绝对高度后 Max；或 Height Blend 逐层（0.7–0.85）；石头 Levels 后加在模糊地面上再减下沉量，与当前高度取 Max（随地形起伏、底部埋土）【Rocky_Ground_A】
- Blur(地面) + 物体 -> Max 一定要乘物体剪影，否则会把裂缝填平【TileFloor】
- 能复制就不用新 Tile Sampler：Safe Transform 偏移 / tile 2 / 旋转已有结果【ForestMirror】

Shape Splatter（v2 SDF 与 v1 图案）
- 链式 background_height + Height Offset 负值（埋入）+ Rotation from Bg Slope + Mask from Bg Slope + Conform to Background；颜色用 Shape Splatter Blend Color 接同一份 splatter data【Cobblestone_01】
- v2 SDF：height_scale 与 1/grid 成正比；density_map_multiplier 1；3D rotation random 1 会让石头竖立【Rocky_Ground_A SDF】
- 密度 = 环带（Blur(R, r) - 顶面）∪ 成团噪声；Mask 只排除顶面 -> 小石斜靠大石侧面【Rocky_Ground_A SDF】

其他
- 密度决定尺寸：点密集处小石、点孤立处大石（Cells 点位由贴图驱动）【80.lv Tom Jacobs】
- Cells + DilationErosion360 膨胀代替多层散布【ConcreteRockField】
- Atlas Splitter + Scan 图集 -> Shape Splatter；Atlas Scatter 带全套 PBR 通道叠在 background 上【Cobblestone_01、RiverPebbles】

## 3 逐块数据（Flood Fill 家族）
- 一次 Flood Fill 处处复用：To Random Grayscale（选块、调粗糙度）、To Gradient（倾斜 / 切面）、To Random Color（向量图）、To BBox Size（大石高小石矮）、Flood Fill Mapper（每块单独贴图）、To Position + Position to Color（延后上色）
- Distance（combine 关）把每块的值扩进缝里，缝隙不出黑线，Warp 和取样更干净【RockCliff_A、tile-04】
- 逐块不同纹理：逐块随机值作 Directional Warp 强度图（强度 300–9408）-> 每块取到噪声不同位置【tile-04、RiverPebbles、TileFloor】
- 逐块方向：Flood Fill -> To Random Color -> Distance 作 Vector Warp 的 vector_map【Cobblestone_01】
- 随机选块：Random Grayscale / Voronoi 随机色 + 极窄 Levels 或 Histogram Select；把 position / range 暴露为图参数【tile-04、RockCliff_A】
- 逐石 ID 与高度一一对应：剪影 + 同 seed 克隆 Tile Sampler + color random 1【Desert_Rocky_Ground_01、Grass_Ground_A】
- 多层 ID：每层自己的 FF Random Grayscale，按哪层在最上（H_n - H_n-1 > 0）逐层覆盖；对合并遮罩只做一次 Flood Fill 会把相连的石头染成同色【Rocky_Ground_A】
- 线太细会让 Flood Fill 渗漏成巨块；Edge Detect -> 腐蚀 -> 膨胀闭合缝隙【TileFloor、ConcreteRockField】
- 逐石 UV：FloodFillAlignedGradient ×2 -> UVConstruct -> UVMapper，纹理顺石头朝向【ConcreteRockField】

## 4 形体塑造
- 随机切面：3–6 个 Flood Fill to Gradient（angle variation 1、不同 seed）连续 Min；封装成 shape_cutter 子图（× bbox size -> Auto Levels -> 减 Uniform -> 与原形 Min）【ForestMirror、Cobblestone_01】
- 屋脊 / 棱柱顶：3 个 FF to Gradient Min × BBox（小块屋脊低）【RockCliff_A】
- 只削顶不削侧：切面 Levels in 0.6 / out low 0.4，保留高侧壁【Rocky_Ground_A v6】
- 逐块倾斜：FF to Gradient × 每块随机强度 -> Levels 输出 1 -> 1 - tilt -> 相乘；angle_input 接大噪声 + 小 variation = 相邻块倾向一致【Beach C、RockCliff_A】
- 体块截面：反相遮罩 -> Distance -> 小 Blur -> 1 - (1 - x)³；低分辨率下用 Blur HQ + Levels 代替 Distance【Beach B / C】
- Slope Blur 用法：Source = Effect = 充气（0.001–0.05）；自喂 Max = 有机团块；Min 削边 0.006–0.02（> 0.1 出同心环、梳齿）；Min 后接 Max = 块面；负强度反向收边【多处】
- 扭曲：MDW 用 64px 低分辨率噪声驱动只扭外形不起毛；Warp 按尺寸递减（大石 0.35 -> 碎石 0.025）【Rocky_Ground_A】
- 劈裂边 / 边缘缺口：剪影 Flood Fill -> 2 个随机方向 FF to Gradient 二值化相乘；剪影边缘带 × Crystal Histogram Scan 咬缺口【Rocky_Ground_A v2】
- Shadows -> Invert -> Subtract = 侧光切削的崩边【Cobblestone_01】
- 中心隆起 MVCenter；倒角 Bevel；Edge Detect 圆角倒圆【ConcreteRockField 等】
- 轮廓抗锯齿：Blur HQ 强度 = K / $size.x，只在 |H - blur(H)| 边缘遮罩内替换【StoneGroundA】
- 地板填坑：Blur 18 -> Levels + 碎石 -> 与原图 Max（防 3D 视图黑斑），地板上必须叠碎石【RockCliff_A】

## 5 裂纹 / 节理 / 层理
- 顺岩形裂纹：Tile Random -> Histogram Scan -> Distance（填色块）-> Crystal Warp 0.22 -> Edge Detect -> Blur 0.2 -> 岩石高度驱动 Directional Warp 46–72 -> 以高度为 Effect 的 Slope Blur Min -> Dilation 加粗 -> Multiply 0.2 / 0.22【DesertRock、Desert_Rocky_Ground_01】
- 细裂纹：Perlin -> Perlin Warp -> Crystal Warp 0.012（锯齿）-> Histogram Select range 0.008 细线 -> × Perlin 分段遮罩【Beach B】
- 直线节理：Tile Sampler 细长 Pyramid 3 方向 × 粗细，rotation map 接 Clouds（0.039）【RockCliff_A】
- 只刻真实块边界：基于每块随机值的 Edge Detect，而不是节理线（避免蠕虫双线）【RockCliff_A】
- 层理：Quantize 8 阶台地 + 51 阶细层理，Shadows 遮罩只放受光面【DesertRock】；Tile Sampler 大 scale 固定角度【SlateCliffRock】
- Cliff 硬线：断裂碎片（Polygon × Gradient Axial）密铺 + 中灰背景 0.5，两个 Tile Sampler Min -> Highpass，只叠在大石内部；稀疏会变成贴上去的板子【Rocky_Ground_A v5】
- 风蚀纹：同一 Clouds 被 Moisture 以 3 个角度 Directional Warp 37 后合成 -> Highpass【Desert_Rocky_Ground_01】

## 6 沙 / 泥 / 积沙
- 沙泥填充：反相岩石高度 -> Non-uniform Blur（anisotropy / asymmetry 拉风向）-> Slope Blur 下滑 -> 填低处 Max【80.lv、DesertRock】
- 沙堆在石脚：石头高度 Blur HQ 9 -> Levels 0–0.34 × Clouds -> Max 沙面 -> 充气 Slope Blur 0.02【Beach A】；StoneGroundA：石头高出地面部分 -> Non-uniform Blur 14 -> Levels × 0.035 -> Slope Blur 3
- 沙被石头推开：用模糊石头高度驱动沙地 Directional Warp 25【Desert_Rocky_Ground_01】
- 石头埋进泥：Height Blend（top 泥、bottom 石，position 0.14）-> mask 输出即泥地遮罩【RiverPebbles】
- 泥地方向拖痕：Multi Dir Warp + 超大 Slope Blur Min（86，自身作 Effect）；全部 AddSub 小强度叠加【Cobblestone_01】
- 积沙：SandAccumulationEffect（半径 12、Intensity 6.5、噪声倍增），积沙色 = 整图 Blur HQ 32【ConcreteRockField】
- 凹处积尘：MG Dust（AO + 法线）【DesertRock、tile-04】

## 7 苔藓 / 植被
- 苔藓遮罩 = Moisture Histogram Scan × 选中石头顶面 Bevel + HBAO 凹处 - 反相 RT AO；MG Metal Edge Wear 找凹处补苔【RiverPebbles】
- 沿流向生长：FlowMap Generator -> Vector Morph 0.004【ForestMirror】
- 苔藓是缝底薄层：苔藓面以原高度为底（不模糊）+ 毯厚 0.004–0.011，用 Max；边缘 = 二值毯 Blur HQ 2.5 ramp + Perlin 噪声 AddSub 0.4 -> Levels 0.40–0.52 窄阈值 + 边外零星点【TileFloor v7】
- 一个遮罩同时驱动苔藓的高度、BaseColor、Roughness、Metallic【TileFloor、ForestMirror】
- 苔藓颜色：暗橄榄 (42,46,28) -> (110,106,64)，不要半透明绿色罩染盖住底材【TileFloor】
- 薄叶片用 Color Tile Sampler 盖章，手动建法线 / AO / 高度，Rotation Random 0；法线按区域整体替换【ForestMirror】

## 8 水
- Water Level 节点：水位做图参数；mask 接噪声让水位有空间变化；sludge、edges wetness、depth blur【RiverPebbles、Cobblestone_01】
- 手动水面：Uniform 灰度 = 水位，Height Blend（contrast 1）参数不变；岸边 Distance 55.9 -> Slope Blur 渐变；浑水色 Copy 0.42–0.57，按深度 HSL 压暗；粗糙度 0【ForestMirror】
- 水下石头：底色 Blur 0.1 + HSL 压暗偏暖，以 水面区域 × 高度 为 opacity 透出【RiverPebbles】

## 9 表面细节
- 细节只加不改大形：Highpass 后 AddSub 小强度（0.01–0.05），层多但每层轻【80.lv、Cobblestone_01】
- 锡纸褶皱：Crystal 1（24 / 40 / 64）高通 AddSub ±0.02–0.06，只在石头上【Beach B / C】
- 细节顺形体流动：用石头自身模糊版驱动 Slope Blur / Directional Warp / Vector Warp【80.lv、DesertRock】
- Slope Blur 磨软的硬边用 Curvature 遮罩还原【80.lv】
- 气孔：小圆点 Tile Sampler Subtract 0.04；BnW Spots Histogram Scan Subtract【Beach B】
- 非无缝 Grunge 先 Make It Tile Patch / Photo【tile-04、Cobblestone_01】
- 噪声复用：噪声库集中放，Transform 偏移 / 旋转代替新噪声；3 级尺度足够【ForestMirror】

## 10 法线 / AO / 曲率 / Height 输出
- Height to Normal World Units（200–300 cm / 20–60 cm）；宏观起伏大时深度不能太小，否则石头只有几厘米高【Rocky_Ground_A v4】
- 法线分区替换：先从最终高度出总法线，再按遮罩把植被 / 玻璃 / 石头换成各自法线；可见部分遮罩 = Blend Divide（层高度 / 最终高度）-> Histogram Scan【ForestMirror】
- 细节法线：RT Bent Normal；沙地区域换 Flat Normal【DesertRock】
- AO：HBAO world units；多 depth HBAO 相乘；BaseColor 用高通后的局部 HBAO【多处】
- 曲率双尺度：宽 = Blur 4 后的高度 -> Normal -> Curvature Smooth（棱线），细 = 原高度（锐边）；边缘 = 宽高 × 细高，单用细曲率会把圆顶当边缘【Rocky_Ground_A SDF v4】
- 曲率阈值与 Normal 强度绑定：改 Normal 强度后重调凹凸阈值【Rock_Cliff_A】
- Height 输出可接 Height Map Frequencies Mapper 重分配高低频【Desert_Rocky_Ground_01】

## 11 BaseColor
- 顺序：调色板（按逐块 ID 取色）-> 纹理斑驳 Overlay -> 矿物颗粒（覆盖约 5%）-> 锈斑 / 污渍 -> 曲率体积 Overlay -> 边缘磨损提亮 -> 缝隙脏污 -> 朝上浮尘 -> 局部 AO 相乘（AO 先映射到 0.5–1 再 × 0.3）-> Sharpen 0.1 -> PBR Albedo Safe Color
- 先定调色板：参考图色度 k-means；逐块分到不同配色（多张 Gradient 用随机遮罩依次 Copy）【Desert_Rocky_Ground_01、Rocky_Ground_A v7】
- 颜色噪声顺形体：Fractal Sum 被高度的 Gradient Vector Warp【DesertRock】
- Get_Slope 区分平面 / 斜面颜色；Shadows 做背光面降饱和【DesertRock、SlateCliffRock】
- 曲率为主色源：Curvature Smooth -> 多个 Gradient；窄 Histogram Select 取等值线做细纹；遮罩 Transformation 偏移后再用，让颜色与形体错开【SlateCliffRock】
- 石英脉 / 深色细裂纹：Perlin -> Warp -> Histogram Select 极窄 -> × 分段遮罩，只在大中石内部【Rocky_Ground_A v7】
- 灰度叠彩色要先 Gradient Map 转色；颗粒用 Copy 中性灰覆盖过大会把颜色洗灰【Grass_Ground_A、Rocky_Ground_A SDF】
- 颜色遮罩里不要大面积低不透明度晕染（变罩色）【TileFloor】
- 照片取色 Gradient 关键帧可从 mirror.sbs / Cobblestone_01 复制【ForestPuddleGround】

## 12 Roughness
- Roughness = Albedo 灰度 -> Levels 反向映射（如 0.1–0.5 -> 0.96–0.70）+ 同一套图案 Overlay + 凸边 -0.08；最直接且与颜色一致【Rocky_Ground_A v4、SlateCliffRock】
- 纯色底 + 噪声叠加：底值与细节量分开控制；每层一个 Uniform 用层遮罩 Copy【ForestMirror】
- 典型值：岩石 0.62–0.84，碎石 0.76–0.88，泥土 0.88–0.96，沙 0.78（湿区 0.55），苔藓 0.62–0.88，釉面瓷砖 0.47，磨光 0.30，水 0
- 逐块 Grunge：Grunge 被逐石随机值 Directional Warp 156，每块取到不同位置【Desert_Rocky_Ground_01】
- 沙粒闪光点处降低粗糙度【DesertRock】

## 13 自定义库节点
- Tom Jacobs（CustomLibrary，SD 16 已验证）：Flood Fills（rocks / bbox / randomgray / randomgradient）、Shift Rocks（RandomMASK 接 Cells 4 原图）、Edge Variation（edge_width 2.16、roundness 10.16）、Add To Ground、Push Edges、Rock Sharp / Shelter 001、Simple Outputs（仅预览）；get_library_nodes('tom jacobs')；create_instance_node(resource_url='FloodFills')
- MV 系列（ConcreteRockField/dependencies）：CellFieldPixelProcessorII、DilationErosion360、StoneBlocks、PostSelectCells、RemoveEdges、MVCenter、MultiChannelDirectionWarp、SandAccumulationEffect、SimpleOutputs
- ForestMirror 依赖：uniform_additive_blending（带自动色阶的高度叠加）、material_tile_sampler（多通道同步）、position_to_color、Bruno_FlowMap_Generator
- 教程节点：Get_Slope、nondirectional_warp、filter_dilation_or_erosion【DesertRock Tutorial nodes】
- 内置替代：uniform_additive_blending 可用 Auto Levels 后 Add；Get_Slope 可用 Normal 的 G 通道近似朝上面
