---
name: sd-material-workflow
description: 用 Substance Designer（SD 16 + SD MCP）新建、迭代或拆解 PBR 材质时使用——制作流程、构建脚本框架、踩坑速查、验证与文档规范。
---

# SD 材质制作流程（SD_Textures 项目）

项目根目录：E:/Work/PersonalProject/SD_Textures（设备 bash 下是 $HOME/mnt/SD_Textures）。软件 SD 16.0.x，通过用户自己 fork 的 SD MCP 插件操作（mcp__remote-devices__substance_designer__*，主力工具是 execute_sd_code）。

配套 skill：
- sd-material-recipes：按材质类别（碎石地 / 岩壁 / 砖石 / 森林地面 / 沙漠 / 有机）选方案和参考文件
- sd-node-techniques：按制作环节（单体、散布、逐块数据、切面、裂纹、沙泥、苔藓、水、法线 AO、BaseColor、Roughness）查节点技巧

## 0. 先判断模式

| 模式 | 触发 | 去哪一节 |
|---|---|---|
| A 新建 | 做一个 XX 材质、给了参考图 | 第 2 节 |
| B 迭代 | 用户看了 SD 3D 视图或截图后给反馈 | 第 3 节 |
| C 拆解 | 分析 / 拆解某个 sbs 的节点流程 | 第 4 节 |

开工前：
1. project_search / project_read 查同类材质的项目文档（claude/sd-*.md），以及 sbs 旁边的 *_节点流程.md
2. 读 sd-material-recipes 的对应类别，确定方案和参考文件
3. 用 AskUserQuestion 确认：参考图、分辨率、输出规格（标准 6 通道还是 OpenPBR）、是否先只做 Height / Normal

## 1. 硬性原则（用户偏好）

1. 所有贴图从最终高度 H_final 派生：Normal、AO、曲率、BaseColor 遮罩、Roughness 遮罩。逐块 ID 可以来自 Flood Fill（由高度二值图得到），或来自与高度同步扭曲的通道；不要用与高度对不上的中间遮罩上色
2. 石子、碎片、杂草、苔藓团：先做单体高度图，再用 Tile Sampler（或 Shape Splatter）在遮罩区域内随机散布，不用 Voronoi 直接生成。例外：石头铺满、互相挤压的密铺材质（碎石场、骨料）可用 Cells + 膨胀方案
3. 默认只用 sbs:// 内置库；自定义库（Tom Jacobs CustomLibrary、MV 系列）需用户同意，并连同 dependencies 一起拷贝
4. 四方连续；2048² Absolute；16 位
5. 先白模（Height + Normal）过关，再做颜色

## 2. 模式 A：新建

### 2.1 参考分析（量化）
- 在云端容器里用 Python 分析参考图：
  - 高度：均值 / std / 偏度；FFT 径向能量分布（如 16–32 周期/tile 的占比）推出岩块尺寸
  - 颜色：亮度高于阈值的受光像素，对色度 (r,g,b)/sum 做 k-means(5)，得到色系和占比。光照已烘焙在参考图里，只取色度，亮度按 PBR 范围重定（照搬参考里的泥土亮度会过暗）
  - 饱和度阈值分区（例：< 0.12 算岩石，> 0.22 算沙）
- 有白模参考就做白模对比；颜色对比放在后面

### 2.2 建包建图
- 图表 $outputsize 必须 setPropertyInheritanceMethod(prop, Absolute) 后再设 (11,11)，否则相对父级会跑成 8192
- 调参阶段可设 1024（10）加速；HBAO 类遮罩最终要在 2048 下复核
- 高度链关键节点 $format 设 Absolute + 16 位，否则 8 位等高线台阶
- 插件 v3.10.1 起 create_graph 默认 2048；新图若是 256，Flood Fill 只能识别零星小块

### 2.3 构建脚本框架（每个材质一套 _build/）
```
<材质>/_build/
  h.py        辅助库：B 构建器（别名 -> 节点、自动排位）、atom() / lib() / wire()、levels / blend / blur / hscan / gradient、preview()、preview_async()、clean_outputs()
  cfg.py      全部可调参数（层表 LAYERS / PASSES、颜色板、强度）
  s1_*.py ... 分阶段：单体 -> 散布 -> 合成 -> 派生贴图 -> 输出 -> Frame
  build_all.py / run.py  删除所有非 output 节点后按 STAGES 顺序整套重建
  s5_frames.py  排版 + Frame + 注释
  s6_export.py  异步导出
  nodes.json  别名 -> 节点 ID
<材质>/_preview/  预览 png 与 _done.txt
```
- 现成可复制的模板：StoneGroundA/_build/（最新、最干净）、Rocky_Ground/_build/
- 每次 execute_sd_code 是新命名空间：先 exec(open(h.py, encoding='utf-8').read())
- **永远用 build_all 整套重建**：只重跑某一阶段会断掉后面阶段的连线，或因函数未定义而失败
- 别名必须唯一：重复别名会让 _reg 删掉还在用的旧节点，整层输出变 0；purge 是前缀匹配（m_b 会连 m_band 一起删）
- 实例节点没有 description 注释，别名另存在 nodes.json
- 库节点要先 loadUserPackage(资源目录/packages/xxx.sbs)；noise_* 包里图 id 没有前缀（noise_perlin_noise 对应 perlin_noise）；HBAO 在 hbao_2.sbs，id 为 hbao

### 2.4 白模 Height（分步做，每步预览）
1. 地面 / 宏观起伏 -> 2. 大石 / 主体 -> 3. 中石 -> 4. 小石 -> 5. 碎石 / 细砂 -> 6. 表面细节 -> 7. 地板填坑 / 抗锯齿 -> H_final
- 每步出预览：俯视灰度、带投影的白模（clay.py，低角度光）、斜视置换（oblique.py，可 CROP=x,y,w 放大，接近 SD 3D 视图）、剖面（profile.py）
- 判断石头是否立在地上，看相对局部地面的高度（H - Blur(H)），不看绝对高度；宏观起伏和堆叠抬升都会吃掉石头的相对高度
- 各级高度要测截断（16 位图在 1 处截断），p99.5 统计

### 2.5 派生贴图（全部来自 H_final）
- Normal：Height to Normal World Units（表面 200–300 cm，深度 20–60 cm 按材质定；DirectX）或普通 Normal 强度 8–15
- AO：HBAO（world units）；BaseColor 里用高通后的局部 HBAO，不要用 World Units AO（会整片压暗洼地）
- 曲率：Curvature Smooth 双尺度（先 Blur 高度再出法线 = 宽尺度）
- 层遮罩 = 合成链相邻两步的高度差 + Levels 阈值

### 2.6 BaseColor -> Roughness
- 见 sd-node-techniques 的 BaseColor / Roughness 两节；收尾 PBR Albedo Safe Color；sRGB 暗部不低于约 30–40
- Roughness 优先由 Albedo 灰度 Levels 反向映射 + 同一套图案，保证与颜色相关

### 2.7 收尾
- clean_outputs 删临时 output；从真实输出反向遍历，删不连到输出的节点
- s5_frames：按别名分组，Frame 标题中英文、描述写做法和关键参数（从 cfg 取值）；注释挂在关键节点上；只用 setPosition，不用 arrange_nodes（会断线）
- 检查：所有节点在 Frame 内、Frame 不重叠、连线数和输出连接不变
- 导出 2048 到 <材质>/Textures 或 Output；验证四方连续（接缝差不大于内部相邻像素差）

### 2.8 文档
- 写或更新项目文档 claude/sd-<材质名>.md（project_write）：文件与图表信息、搭建脚本、流程结构、关键参数表、版本记录（反馈 -> 原因 -> 改法 -> 数值结果）、踩坑、已知差距 / 下一步
- 新踩到的通用坑，同时补进本 skill 的第 5 节（提议更新 skill）

## 3. 模式 B：迭代（用户反馈）
1. **先诊断再改**：把反馈翻译成可测量的量。例：边缘硬线 -> 统计缝两侧每列法线符号一致性；黑斑 -> 查 BaseColor 暗像素、Height 局部深坑（h - Blur40 < -0.18）、AO 最小值；凸出 -> 导出前后高度相减看抬高量
2. 改前备份（*_vN_backup.sbs 或 _build_vN_backup/），版本号 +1
3. 只改定位到的环节，整套重建，出对比图（vN-1 / vN / 参考 并排）
4. 用数字汇报：覆盖率、均值、p5/p95、相对高度、截断比例
5. 若新版本整体不如旧版，果断回退结构，只保留有效部分（Rocky_Ground_A v8 的教训）
6. 更新项目文档的版本记录

规则亮边 / 直线排查顺序：曲率提亮 -> 粗糙度边缘磨亮 -> 高度 1px 悬崖 -> 8 位高度转法线 -> 轮廓本身就是直线（乘原始 Tile Generator 会把所有扰动切回直线）。

## 4. 模式 C：拆解第三方 sbs
1. 在 SD 里打开，get_graph_info 拿节点、Frame、注释、输出；按 Frame 或 x 坐标分段遍历连线
2. 出预览：sheet.jpg（BaseColor / Height / Normal / Roughness）放 _preview_xxx/
3. 写 <名字>_节点流程.md 放在 sbs 旁边，同时 project_write 到 claude/sd-<名字>-breakdown.md。固定结构：
   - 文件信息：路径、图表名、节点数、分辨率、输出、成品描述、依赖（自定义节点要列出并提醒连同 dependencies 拷贝）
   - 核心思路（引用图中注释原文）
   - 一、整体架构（ASCII 流程图）
   - 二…N、按 Frame 展开：节点链 + 关键参数
   - 可复用技巧清单（编号）
   - 与本项目偏好的对照：是否从最终高度派生、是否单体 + 散布；可清理节点（opacity 0、强度 0、未接输入的直通节点）
4. 拆解得到的新技巧，归纳进 sd-node-techniques / sd-material-recipes（提议更新 skill）

## 5. SD 16 / MCP 踩坑速查

枚举（SD 16 实测）
- Blend blendingmode：0 Copy / 1 Add / 2 Subtract / 3 Multiply / 4 AddSub（底 + 2×源 - 1）/ 5 Max / 6 Min / 7 Switch / 8 Divide / 9 Overlay / 10 Screen / 11 Soft Light；没有 13。MCP 内置文档写成 4 = Max 是错的；新 Blend 用两张 Uniform 实测一次
- Slope Blur Grayscale 2 mode：5 Max / 6 Min / 7（或 0）Blur
- Tile Sampler：pattern 1 = Image Input；blending_mode 1 = Max（自己的枚举，与 Blend 不同）；color_parametrization_mode 0 Color / 1 Scale（高度随大小）/ 2 行 / 3 列 / 4 Pattern index
- Shape pattern：3 Paraboloid / 4 Bell
- Normal inversedy=False 是 DirectX

数值行为
- Histogram Scan：Position 越大白色越多
- Levels levelinmid > 0.5 变暗（凹），< 0.5 变亮（凸）
- Tile Sampler mask_map_threshold：mask > 阈值才保留，值越低留下越多；没接 mask 时阈值 > 0 会过滤掉全部实例
- Tile Sampler 的 color 参数不会压低图案高度 -> 每层后接 Levels 控高度
- Tile Sampler 石头直径约 0.48 × scale / grid；格子半径 + position_random 超过约 1.1 格会在格子边界切开石头
- Blur / Blur HQ intensity 是相对尺寸（2048 下 Blur 1.0 约每边 16 px）；要固定像素宽度用 $size 函数驱动；atomic Blur 小于约 0.1 无效
- Atomic Warp 强度单位很大，0.06 左右；Directional Warp 小于 1 几乎看不出，逐块偏移用 300–9000
- Distance 单位远大于像素；Distance 40 在 2048 下慢 15 倍，12 就够
- Bevel distance 为负是向内，-0.01 约 2048 下 10 px
- Edge Detect 输出是白底黑边，要与遮罩 Multiply，不能 Subtract
- Height Blend 的 top 恒 >= bottom 时 height_mask 全白；叠加型图层给 bottom 加一个 ε
- 灰度 source 混到彩色 destination 上无效：先 Gradient Map 转彩色，或用灰度作 opacity 混两张彩色 Uniform
- Transformation 默认平铺：缩放 / 拉伸单体要设 $tiling 0
- curvature_smooth_v2 的 radius 不起作用，用 curvature_smooth + 先 Blur 高度
- Shape Splatter v2 石头高度不随 x/y_amount 缩放：height_scale 与 1/grid 成正比；mask_map 是硬阈值；density_map 要 multiplier 1；Poisson 模式 amount 无效
- shape_splatter_mapper 默认输出 8 位：写进高度前设 16 位
- 噪声参考中位值：Crystal 约 0.09、Dirt 3 约 0.11、Moisture 约 0.53，作遮罩前先归一化；Creased 有方向条纹、Dirt 3 有类字母图案

性能
- FX-map 噪声大 scale 极慢（BnW Spots 3 在 96 / 128 时约 10 分钟，约与 scale² 成正比）：细颗粒改 white_noise_fast -> Blur -> Levels
- Tile Sampler 实例 >= 380² 或接 scale_map_input 会让整图 > 60 秒
- 设备 VM 内存约 4 GB，SD 里没有 numpy：预览缩到 1024、float32

MCP / Python
- MCP 调用超过约 60 秒会超时，但 SD 仍在算：用 QTimer.singleShot 异步执行，回调挂在 builtins 上防回收，轮询 _preview/_done.txt；不要立刻重复调用
- graph.compute() 只保证算到接了 output 的节点：预览 / 导出时临时挂 output 节点，用完删除
- 不要对输出节点的连线调用 disconnect()（会卡死或返回空）；直接新连一条会替换旧线；断线用 disconnect_nodes 工具
- 连错端口时 MCP 只返回 {}：连线前检查端口名
- 读含中文的脚本 open(..., encoding='utf-8')；Gradient Map 关键帧：gradient_key_rgba 结构体 pushBack 到 SDValueArray；枚举参数用 SDValueInt
- 中途中断会留下孤立节点：删除 nodes.json 之外、非 output 的节点；测试用临时包要 unloadUserPackage
- 16 位 PNG 在 PIL 里是 I;16，要除以 65535

## 6. 交付前验证清单
- [ ] 所有输出都从 H_final 派生（逐项说明来源）
- [ ] 四方连续（接缝差 <= 内部差）
- [ ] Height 无截断（p99.5 < 1），无 8 位台阶（关键节点 16 位）
- [ ] 斜视置换 / 白模与参考对比过；必要时 SD 3D 视图截图确认
- [ ] BaseColor sRGB 范围合理（暗部 >= 30–40），PBR Validate 无红
- [ ] Roughness 范围与材质匹配（岩石 0.6–0.85、泥土 0.85–0.96、水 0–0.05）
- [ ] 无临时 output、无孤立节点；Frame / 注释已更新
- [ ] 导出贴图、项目文档已写入
