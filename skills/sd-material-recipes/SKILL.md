---
name: sd-material-recipes
description: 按材质类别选 Substance Designer 配方——碎石地、卵石滩、沙漠、岩壁悬崖、板岩层理、砖石瓷砖石板路、森林地面苔藓水洼、血肉有机，给出骨架、参数起点与参考文件。
---

# SD 材质配方库（按材质类别）

先按类别找到配方，再去读参考文件拿细节。制作流程、脚本框架、踩坑见 sd-material-workflow；单个技巧的做法见 sd-node-techniques。

参考文件位置：
- 项目文档：project_read claude/sd-*.md（下文写作 [doc:名字]）
- 本地拆解：E:/Work/PersonalProject/SD_Textures 下各 sbs 旁的 *_节点流程.md（下文写作 [md:路径]）

## 类别索引

| 类别 | 关键词 | 首选方案 | 最佳参考 |
|---|---|---|---|
| 1 碎石地 / 岩石地面 | rocky ground、rubble、gravel、碎石、山地碎石 | 1A 单体 + 多层 Tile Sampler，或 1B SDF Shape Splatter | Desert_Rocky_Ground_01、StoneGroundA、Rocky_Ground_A |
| 2 密铺碎石 / 骨料 | concrete aggregate、碎石场、砾石层 | Cells + 膨胀 | ConcreteRockField |
| 3 卵石滩 / 河滩 / 沙滩岩石 | pebbles、river bed、beach | 6 层 Tile Sampler + 泥 + 水 | RiverPebbles、Beach_Rocky_Ground_A/B/C |
| 4 沙漠 / 沙地 / 基岩 | desert、bedrock、dune、沙纹 | 岩板单体 + Quantize 层理 + 沙地 | DesertRock_Tutorial |
| 5 断裂岩壁 / 悬崖 | cliff、fractured rock、节理 | 节理分块 + Flood Fill 屋脊 | RockCliff_A |
| 6 层状岩 / 板岩 | slate、stratified、页岩 | 单块楔形 + 大 scale 固定角度 Tile Sampler | SlateCliffRock 14 |
| 7 砖石 / 瓷砖 / 马赛克 / 石板路 | tile、mosaic、brick、cobblestone、flagstone | 规则网格 + 逐块随机值 + 勾缝 Height Blend | tile-04、HavanaStoneFloor、TileFloor、Cobblestone_01 |
| 8 森林地面 / 植被 / 苔藓 / 水洼 | forest floor、moss、leaves、puddle、grass | 按通道分行 + 层遮罩 + Position Map | ForestMirror、ForestPuddleGround、Grass_Ground_A |
| 9 有机 / 血肉 | guts、flesh、organic | 噪声 + 扭曲 + Slope Blur 自喂 | BloodyGuts |

---

## 1 碎石地 / 岩石地面

### 1A 单体 + 多层 Tile Sampler（项目偏好的标准做法）
参考：[md:Desert_Rocky_Ground_01/Desert_Rocky_Ground_01_节点流程.md]、[doc:sd-rocky-ground-a]、[doc:sd-beach-rocky-ground-c]
```
单体石头 ×4–6 -> L1 大石 Tile Sampler -> L2 -> L3 -> L4（逐层只填空隙）
 -> 石面细节 -> 地面 Height Blend -> 地面再撒细碎石 -> H_final
```
- 单体：Shape / Polygon 2 / Cube 3D 起形 -> Warp 打破轮廓 -> 3 个 Gradient Axial 或 Flood Fill to Gradient 连续 Min 切面 -> Edge Detect 圆角倒边
- 层表起点（Desert_Rocky_Ground_01）：6×6（mask random 0.81，很稀）-> 20×20 -> 30×30 -> 125×125
- 下一层 Scale Map = 上一层 HBAO 反相（靠近大石的更小），Mask Map = 上一层反相 Histogram Scan（只放空隙）
- 合成：Height Blend 逐层（position 0.7–0.85）；小石先 Min 一个 Histogram Range 压低。或每层先 Levels 定绝对高度再 Max
- Rocky_Ground_A 层表（grid / scale / 高度）：A 8 / 1.37 / 0.60，B 22 / 1.35 / 0.38，C 38 / 1.75 / 0.30，D 56 / 1.7 / 0.19，E 100 / 1.8 / 0.11；石头放在模糊地面 H_glow 上再减下沉量，与当前高度取 Max
- 密度场：大石 = Clouds Histogram Scan；中小石 = max(大石邻近光晕 Blur, 成团噪声) × (1 - 上一层膨胀足迹)

### 1B SDF Shape Splatter v2（真实体积、石叠石）
参考：[doc:sd-rocky-ground-a-sdf]、[doc:sd-stone-ground-a-mountain-rubble]（模板 StoneGroundA/_build/）
- 每个 pass 的 background_height = 前面所有 pass 的合成；height_offset_from_background 1、slope_rotation 1、smooth_background_slope 0.4 -> 新石头落在旧石头上并顺坡
- SDF：rock（facets 7–10，randomness 0.85–0.95）morph 少量椭球 + simplex；height_scale = 0.96 × hd × 9 / grid
- 密度：大石只在地形顶带（t_band 0.5–0.85）× 成团噪声；后续层 = 前一层外环（Blur(R) - 顶面）∪ 噪声；碎石 = HBAO 缝隙 × 石头附近遮罩
- 必做：轮廓抗锯齿（Blur HQ 强度 = K / $size.x，只在 |H - blur(H)| 边缘遮罩内替换）
- 再加：Curvature 双尺度边缘崩口写进高度（-0.005）

### 1C Tom Jacobs Cells 链（快速出铺满碎石）
参考：[doc:sd-80lv-rocky-ground-tom-jacobs]、[doc:sd-customlibrary-tom-jacobs-nodes]
```
Cells 4 (scale 7) -> Edge Detect -> Flood Fills.rocks -> Shift Rocks.Rocks
Cells 4 原图 -> Shift Rocks.RandomMASK；Cells 4 -> Edge Variation.heightmask
Shift Rocks -> Add To Ground(Top, Bottom = 地面) -> Push Edges -> 出图
```
- 缺点：Edge Detect 缝线会在石头边留细脊、石头像台地（StoneGroundA v1 已因此换 SDF）

### 常见问题
- 石头像埋在地里：宏观起伏 / 堆叠抬升吃掉了相对高度 -> 看 H - Blur(H)，减小下沉、提高侧壁（切面 rin 0.6 / rlo 0.4）
- 碎石沿地面起伏排成蜂窝网格：地面中频太密 -> 地面平滑化，碎石密度限定在石头附近
- 碎石像硬币 / 钢珠：Tile Sampler color 不压高度 -> 每层 Levels 控高度；小物体不要用 Slope Blur 充气（会变平台）
- 石头太像原型：大石用 6 个专用剪影（不同边数、非等比拉伸、两条 Gradient Axial 直切边）

## 2 密铺碎石 / 骨料（ConcreteRockField）
参考：[md:ConcreteRockField/ConcreteRockField_节点流程.md]（大量 MV 自定义节点，在 dependencies/）
- 核心：一张逐格随机灰度的细胞图 -> DilationErosion360（距离 15、200 步）亮格压暗格 -> 自然得到层叠半埋
- Edge Detect -> 腐蚀 2 -> 膨胀 2 闭合缝隙 -> StoneBlocks（Flatness 0.52）-> RemoveEdges -> MVCenter 中心隆起 -> PostSelectCells 把膨胀值 / 噪声按格取值做逐石高低
- MultiChannelDirectionWarp 用同一组角度 / 强度同时扭曲高度和 3 张遮罩（颜色永远对齐）
- SandAccumulationEffect：小半径平滑边缘，大半径 + 噪声倍增做积沙，输出积沙遮罩；积沙颜色 = 整图 Blur HQ 32
- 内置库替代：Tile Sampler color_random + Max 混合，亮的在上并决定高度（Beach_Rocky_Ground_C 已用）

## 3 卵石滩 / 河滩 / 沙滩岩石
参考：[md:RiverPebbles/SBS/RiverPebbles_节点流程.md]、[doc:sd-beach-rocky-ground-a]、[doc:sd-beach-rocky-ground-b]
- 单块卵石：Shape 圆 -> Perlin 驱动 Multi Directional Warp 39 -> 3 个 Flood Fill to Gradient Min -> Non-uniform Blur 5.9 磨圆 -> Crop 拆 4 块
- 6 层 Tile Sampler：8² / 14² / 22² / 40² / 60² / 80²，Mask Map = 上一层 Histogram Scan -> Bevel -> 反相（Bevel 距离 = 石间距）；Scale Map 和 Color Map 共用一张 Moisture（成片分布）
- 泥：Height Blend（top 泥、bottom 卵石，position 0.14）-> 卵石半埋，mask 输出即泥地遮罩
- 水：PBR Base Material 打包 -> Water Level（水位做成图参数）；水下石头 = 原底色 Blur + HSL 压暗，以 水面区域 × 高度 为 opacity 透出
- 沙滩：沙堆在石头底部 = Blur HQ 9(石头) -> Levels 0–0.34 × Clouds -> Max 沙面；沙上碎石 Add 到沙面上（不要切进沙里）；接触线带内用模糊高度 Copy 0.8 柔化
- 模糊版叠硬版本要用 Min，不用 Copy（否则轮廓外一圈裙边）

## 4 沙漠 / 沙地 / 基岩
参考：[md:Daniel Thiger - Tutorial Desert Bedrock（Substance Designer 沙漠基岩制作教程）/DesertRock_Tutorial_节点流程.md]、[doc:sd-desert-bedrock-tutorial-breakdown]
```
岩板单体（Cells + Polygon -> 两次 Slope Blur Max）-> Tile Sampler 4×4 -> Directional Warp
 -> Quantize 8 阶台地 -> 裂纹 -> Quantize 51 阶细层理（只在受光面）
 -> 沙地（低处阈值 + Non-uniform Blur 拉风向）-> 沙纹 -> 碎石（MG Dust 遮罩）-> 柔化沙地
```
- 沙纹：两个 Gaussian Tile Sampler 互相 Directional Warp + Curve；用沙地形状的 Gradient 做 Vector Warp（强度 -0.01）让沙纹顺沙堆弯
- 碎石推开沙子：以碎石遮罩为 Effect 的 Non-uniform Blur，再 Add 碎石
- 沙粒闪光：White Noise 原图 + 旋转 ±90° RGBA Merge 成随机法线，只放在稀疏点和沙地，粗糙度同步降低
- 岩面细节法线用 RT Bent Normal，沙地区域换平面法线
- 沙漠碎石地（红褐沙 + 多级碎石）用 1A 方案 + Desert_Rocky_Ground_01 的沙地：用石头高度驱动沙地 Directional Warp（沙被石头推开）

## 5 断裂岩壁 / 悬崖
参考：[md:Rocks_A/RockCliff_A_节点流程.md]、[doc:sd-rockcliff-a-whitemodel]、[doc:sd-rock-cliff-a]、[doc:sd-rocks-a-fractured-cliff]
```
1 节理：6 个 Tile Sampler 细长 Pyramid（3 方向 × 粗细）+ Voronoi 大裂隙 + 局部细分 -> Flood Fill（约 1400 块）
2 岩板：随机高度 + 倾斜（angle_input 接大噪声、angle variation 0.15）+ 3 向屋脊（3 个 FF to Gradient Min）× BBox -> 刻真实块边界 -> 发丝裂纹 -> 抬到 0.5–0.98 × 岩体分区
3 碎石：岩体 Blur 填充面 + 5 尺度 Voronoi 碎块，只在岩体以外
4 合成：Crystal 凿面 -> 两次 Warp -> Slope Blur Min（<= 0.02）-> Max 碎石 -> 微细节 -> Blur 18 + Max 地板
```
- 节理 rotation_map 接 Clouds（multiplier 0.039）-> 缓慢偏转；分区按整块决定（Flood Fill to Grayscale + 极窄阈值）
- 坑：基于节理线的 Distance / 肩部效果会在死胡同线两侧生成成对的蠕虫凸脊 -> 只用基于每块随机值的 Edge Detect（真实边界）
- 坑：倾斜岩面上 Slope Blur > 0.02 会拉出平行条纹；大面积 Max 填平要叠碎石，否则是平滑空地
- 颜色参考：均值 sRGB (138,123,110)；深缝暖且饱和 (69,57,48)，凸棱偏白 (196,182,167)
- 若要符合偏好：碎石可改 单块棱角碎石 -> Tile Sampler（Mask Map = 岩体反相）

## 6 层状岩 / 板岩
参考：[doc:sd-slatecliffrock-14-breakdown]、[doc:sd-stratified-rock-material]
- 单块楔形：Polygon 2 -> Quad Transform -> 旋转 46° -> × Gradient Linear
- Tile Sampler 13×13，scale 36（远大于格子，大量重叠），rotation 固定 0.857、random 0.03 -> 层理；Scale / Color / Distribution Map 共用一张 Gaussian Noise
- 拉伸剪切的 Crystal 相减 -> 同方向长刻痕；多级 Directional Warp 让层理弯折；Slope Blur Min 后接 Max 出块面
- 两个尺度 Cells 3 -> Edge Detect -> Bevel -> Slope Blur 做碎裂板块，Clouds 遮罩局部叠加
- 颜色主要来自最终曲率；铁锈纹 = 曲率极窄 Histogram Select（range 约 0.04）；Roughness = BaseColor 反相 Levels
- 简版层状岩：Tile Sampler（Gradation，3×9，旋转 0.95）+ 方向运动模糊收端头

## 7 砖石 / 瓷砖 / 马赛克 / 石板路
参考：[md:TileSet/tile-04_节点流程.md]、[doc:sd-havana-stone-floor]、[doc:sd-tilefloor-broken-inlay]、[doc:sd-cobblestone-01-breakdown]
```
图案形状（Tile Generator 网格 / Splatter Circular 环 / 旋转 45° 菱形）-> Multi Switch(Pattern)
 -> 逐块数据（Flood Fill -> Random Color -> Distance -> R 通道 = #408）
 -> 砖体（Bevel -> Slope Blur 啃边 -> 逐块高差 / 倾斜 / 逐块噪声 / 裂纹 / 破损 / 崩边）
 -> 勾缝（从砖形状反推）-> Height Blend(position 0.4) -> H_final
```
- 逐块噪声：Directional Warp 强度 500–9408，强度图 = #408 -> 每块取到噪声不同位置
- 参数化选块：Histogram Select 的 position / range 暴露为图参数（裂纹、破损、崩边、灰尘）
- 一个 Pattern 参数同时切换高度和配色（两个 Multi Switch）
- 不规则砖轮廓（Havana v8）：在 Tile Generator 的 Bevel 线性距离上加噪声再阈值化；不要 × 原始 Tile Generator（会切回直线）
- 勾缝高度跟随相邻砖（加权平均，低砖主导）；缝带模糊后要加回颗粒，否则是光滑胶条
- 石板路（Cobblestone_01）：Tile Random -> Distance 填满 -> Cutting Planes（5 个 FF to Gradient Min）-> Shadows 反相切边 -> 20 多层低强度细节；缝里 Shape Splatter 撒碎石 / 树枝，Atlas Scatter 撒苔藓落叶
- 破损镶嵌（TileFloor）：苔藓是贴着缝底的薄层（Max，不要 AddSub），边缘用 Blur ramp + 噪声 AddSub + 窄阈值打碎
- 对外参数参考 Havana：Tile_Tilt 0.06、Tile_Height_Variation 0.03、Mud_Overflow、Polish_Amount、Crack_Amount、Edge_Damage、Dirt_Amount

## 8 森林地面 / 植被 / 苔藓 / 水洼
参考：[md:JRO_Nature/JRO_ForestMirror/mirror_节点流程.md]、[doc:sd-forest-puddle-ground]、[doc:sd-grass-ground-a]
- 布局：噪声库放最左复用；主图按通道分行（Height / Position / Roughness / Metallic / BaseColor），每加一层在同一列各放一个 Blend，用同一个层遮罩
- 泥地：BnW Spots 2 三个版本各自 Source = Effect 的 Slope Blur（0.05 / 0.019 / 0.004，充气）
- 石头层：L1 Cells 石头（无穿插）-> L2–L4 Tile Sampler（7² -> 10² -> 17² -> 33²），mask = 上一层 HBAO -> Blur -> Levels，invert；每块过 shape_cutter；Uniform Additive Blending 或 Auto Levels 后 Add
- Position Map 延后上色：每层 Flood Fill to Position 累积，最后 Position to Color 一次取色
- 树枝 / 碎玻璃 / 叶簇：子图生成器 + Tile Sampler；能 Safe Transform 复制就不用新 Tile Sampler
- 薄叶片：Color Tile Sampler 盖章，法线 / AO / 高度手动构建；法线按区域替换
- 苔藓：HBAO 反相 + FlowMap Vector Morph 沿流向生长；苔藓遮罩 = Moisture × 石头顶面 + AO 凹处
- 水：Uniform 灰度控制水位（Height Blend 参数不变），岸边 Distance 渐变 + 浑水色 + 按深度压暗；水面粗糙度 0
- ForestPuddleGround 数据：BaseColor 中位数约 0.26、AO 中位数约 0.8；调色板可直接从 mirror.sbs 复制 Gradient 关键帧
- 草地（Grass_Ground_A）：落叶下地面先 Blur HQ 6 抹平；单叶 ID / 细节用克隆的 Tile Sampler（参数含 $randomseed 全复制）

## 9 有机 / 血肉
参考：[doc:sd-bloody-guts-breakdown]
- 一条高度主干：Perlin 软光叠加 -> Directional Warp -> Slope Blur 自喂（Max，Effect = 自身 Blur HQ）约 15 次出团块
- Blur HQ -> Slope Blur -> Blur HQ 三明治；叠加主要 Soft Light，挤缝 Multiply，凸起 Screen，凹陷 Subtract（0.03–0.5）
- 血管：Cells 1 -> Slope Blur Max -> Non-directional Warp -> 主干驱动 Directional Warp -> Invert -> Screen 0.04（双尺度）
- 颜色：肉色 Gradient + 静脉青蓝 (0.12,0.21,0.26)；血用带 alpha 的 Gradient Map 以曲率作 opacity 只加在低洼
- Roughness：强法线（60）出曲率双路 Screen -> 0.14 到 0.55 插值；湿血区 Subtract

---

## 选方案的决策规则
- 石头稀疏散布在地面上 -> 1A；要真实体积、石叠石、顺坡 -> 1B；石头铺满互相挤压 -> 2
- 竖直岩壁、块状断裂 -> 5；斜向层叠 -> 6；水平层理台地 -> 4 的 Quantize
- 规则几何 -> 7（网格 + 遮罩，不用 Tile Sampler）
- 多种物体混合的地表（泥 + 石 + 植被 + 水）-> 8 的分行布局 + Position Map
- 拿不准时先做 1–2 个方案的白模小样（1024）给用户对比
