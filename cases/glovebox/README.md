# glovebox：handleBase 历史回放案例

本目录的 handle_base/ 是手套箱把手底座导出包，来自 D:\console_box\AI_CAD\construct_steps-handleBase\construct_steps-handleBase。保留了原始源码、步骤 JSON、模型信息、设计意图表、引用数据和 native 模板，省略解释器缓存。案例用于研究 Python 控制 CATIA、提取命令和比较参数变体。当前入口包括离线检查程序 verify.py，以及下文的新实现圆形凸台子流程 pipeline.py；完整历史 CAD 回放仍缺原项目上层运行器。

## 运行环境与入口

从仓库根目录打开 PowerShell，执行以下命令。首次准备新机器时可用同架构的 Python 3.13 创建 .venv，再安装 requirements.txt。已准备的机器可直接从第三行开始。离线机器可从预先准备好的 wheel 目录用 pip install --no-index --find-links <目录> -r requirements.txt 安装。
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe cases/glovebox/verify.py
```
检查程序初始化本机 COM，读取步骤清单，核对每个 JSON 的步号、特征 ID，并打印步骤 794、795 的特征类型。它不打开 CATIA。失败时根据异常中的文件或模块名定位。

## 历史包怎样调用

| 文件或目录 | 作用与输入输出 |
|---|---|
| __init__.py、model_info.py | 暴露固定模型目录、参数、公式、可见性及规则等导出元数据。 |
| sequence.py | 提供按依赖排列的步骤名和原特征 ID。它是清单，不启动 CATIA。 |
| step_*.json、_step_loader.py | load_step 读取一步的 RECORD、DEFINITION、DEPENDENCIES 和 GEOMETRY，用 RECORD.type 查 HANDLERS，返回构建函数与该步数据。 |
| _handlers.py | 注册几何处理函数，为 Reconstructor/ModelData 提供重建与校验逻辑；包含 V5 文档、测量、模板复制及面边引用调用。导入时即依赖上层运行器。 |
| handlers.py | 创建实体或几何容器的辅助函数；创建实体时临时切换 HybridDesignMode 并恢复。 |
| references/、native/ | 前者为按块导出的引用数据，后者为部分曲线、曲面处理所用的 CATPart 资产。保留相对目录。 |
| merge_design_intent.py、add_columns_design_input.py、merged_design_intent.csv | 把细粒度步骤整理为设计意图，并补充输入与可变参数说明。属于 CSV 整理工具，重跑可能改写案例表格。 |

从数据到几何的预期顺序是：上层运行器准备 CATIA 会话和 Part 上下文 → 按 sequence 取步骤 → load_step 装入 JSON → 解析上游支撑与容器 → 调用对应 handler → 更新模型并验证。此包没有提供可证实的完整启动命令。在现有来源范围内缺少包内相对导入的 common、sketch_geometry、reconstruction、model_data；应取得匹配原版本的源码、父包结构及原启动示例。这些属于项目代码，不能用同名 PyPI 包代替。

## 用 794–795 步准备方向盘迁移

794 是受终止面约束的凸台，795 使用给定出模方向、支撑面和角度创建拔模。两步有更早的前置引用，不能从空模型只运行这两步。先在匹配历史环境的完整上下文回放默认样件，记录实际命令、补丁、生成对象与测量结果。把角度作为候选设计输入，由工程师确认单位和允许范围；终止面、出模方向与引用关系要显式保留。默认值核对原几何，合法变体核对人工变体，违规值核对 DS 的失败原因。上述 CAD 结果均待实测。

迁移方向盘时先选择工程师可独立演示的一段偏置或加厚，记录原值、单参数变体和人工拾取对象。仅当两案例对输入、输出及更新行为的要求一致时，共用操作命令。R2022x 的模板复制、保存重开、BRep 引用重绑和测量接口分别实测。最终让命令行与本地 Skill 提交同一组参数，比较模型与 DS 结果。

## 已实现的圆形凸台子流程（2026-11-14）

`pipeline.py` 是新实现的限定子流程执行器，直接读取原始步骤 JSON。真实几何依赖为：底部平面 249、顶部支撑面 671 → 草图 701 → 以平面 249 为终止面的凸台 794。圆半径是可变输入，默认值约 5.5 mm；圆心和草图坐标系保留历史求值结果。完整历史回放仍缺上层运行器。

两张平面采用导出的求值后方程，草图采用导出的求值后坐标系。OriginPt（步骤 205）定位关联及相合、相切约束没有恢复；原 DEPENDENCIES 未完整包含这些定位引用。当前只验证冻结定位下的圆形凸台，不包括拔模 795，也不代表整个手套箱已重建。默认几何通过解析体积与 CAD 测量对照，尚未与完整原件逐面比对。

### 文件作用与调用流程

| 文件 | 职责 |
|---|---|
| pipeline.py | 校验请求及源特征身份，建立平面检查点，创建草图和凸台，保存重开测量，检查失败后恢复 |
| pad_pipeline.json | 保存已支持的阶段、测量容差及总尝试上限；不能任意重排有依赖的步骤 |
| default.json | 默认半径通过的回归请求 |
| recovery.json | 先用 5.0 mm 失败，再用约 5.5 mm 通过的恢复请求 |
| no_solution.json | 候选耗尽后返回无解的请求 |
| tools/glovebox_agent.py（仓库根目录） | 加载 Skill，调用 Qwen 兼容接口，执行模型工具请求并返回测量摘要 |
| .agents/skills/glovebox-design/SKILL.md（仓库根目录） | 设计意图识别、参数单位、能力边界、失败恢复和结果解释规则 |
| tools/verify_glovebox_pipeline.py（仓库根目录） | 实机检验恢复、同参重建、保存重开、无解和检查条件不可变 |
| tools/test_glovebox_agent.py（仓库根目录） | 隔离网络与 CAD，测试模型入口的状态和退出码传递 |

实际执行顺序为：读取配置和历史 JSON → 创建独立测试 Part → 建立两张平面及空 Body → 保存检查点 → 打开检查点副本 → 按半径创建草图 701 → 创建以平面 249 为终止面的凸台 794 → 保存关闭并重开 → 独立测量体积和面积 → 判断通过或保留失败记录并恢复重试。

从仓库根目录 `D:\ai_cad` 运行：

```powershell
.\.venv\Scripts\python.exe cases/glovebox/pipeline.py cases/glovebox/default.json
.\.venv\Scripts\python.exe cases/glovebox/pipeline.py cases/glovebox/recovery.json
.\.venv\Scripts\python.exe cases/glovebox/pipeline.py cases/glovebox/no_solution.json
.\.venv\Scripts\python.exe tools/verify_glovebox_pipeline.py
```

成功返回退出码 0，无解返回 2，执行异常返回非零。每次新运行创建独立测试文档，不修改用户已有 Part。失败件保存后关闭，成功件保持打开以便肉眼检查。恢复使用检查点副本并重新获取 COM 对象，不在用户模型中删除特征。

### 参数、检查与恢复

可变参数是圆半径，单位 mm。输入必须为有限正数，每个运行最多四次尝试；模型入口还受调用端给定的上下限约束。最低体积和规则来源由调用端固定，模型只能提出候选半径，不能修改检查阈值。

示例中的最低体积 1300 mm³ 是回归测试条件，不是 DS 规范。实测半径 5.0 mm 的体积约为 1128.915725 mm³，未通过；半径 5.5 mm 的体积约为 1365.988028 mm³，通过。保存重开后测量一致，恢复结果与同参数从头构建一致。报告中 DS 状态为 `not_evaluated`。

输出位于 `runs/glovebox-pad-*/`：request.json、plan.json、checkpoint.CATPart、checkpoint.json、每次 attempt 的 CATPart 与 JSON，以及 result.json。记录源数据指纹、实现指纹、检查点指纹、参数、测量和失败原因。

执行器 `run(..., resume_run=运行目录)` 支持同检查点续跑，仅允许 `no_solution` 状态继续；源数据、实现、流程和检查条件必须保持一致，总尝试数不能超过上限。CLI 默认新建运行；模型调度程序自动复用同一运行。成功和执行异常后不能直接重复调用建模。

### Skill 与模型调用

在 Git 忽略的 `.env.local` 中配置 QWEN_BASE_URL、QWEN_MODEL、QWEN_API_KEY，字段示例见根目录 `.env.example`。不要在源码、命令行参数、日志或提交中放入 Key。

本轮用户选择以已验证的公网 Qwen API 为开发验收，本地推理部署留到正式阶段。公网调用须显式使用 `--allow-cloud`；默认拒绝公网，没有公网回退。正式本地推理尚未实测。发送给服务端的内容为需求、Skill、参数范围和检查摘要，不包含 CAD 文件或历史 JSON。

```powershell
.\.venv\Scripts\python.exe tools/glovebox_agent.py "建立手套箱圆形凸台，先试半径5毫米，读取失败结果后再试5.5毫米。这是恢复回归测试。" --radius-min 5 --radius-max 5.5 --minimum-volume 1300 --check-source "恢复回归用例，非DS" --allow-cloud
```

模型可预先给出候选列表，也可先提交一个候选，读取失败测量后再提出下一候选。两次调用复用同一检查点。普通咨询不应启动 CAD；模糊要求应先澄清，不得声称已经建模。最终以 result.json 的 CAD 状态为准，不能仅凭模型措辞判断成功。

模型入口同样在 `no_solution` 时返回 2，在 `passed` 时返回 0。普通咨询输出 `not_executed`。离线状态传递测试如下，它不代表本地模型推理验证：

```powershell
.\.venv\Scripts\python.exe tools/test_glovebox_agent.py
```

动态 Qwen 实测记录位于 `runs/glovebox-pad-20261114-123339-552375/`；CAD 集成报告位于 `runs/glovebox-pad-20261114-123443-632476/integration-verification.json`。这些记录对应修复文档编码之前的运行；修复后 Skill 的新运行另行保存并记录 Skill 指纹。

方向盘迁移可复用执行入口、检查点与独立测量机制；支撑面、参数含义、冻结策略及 DS 阈值必须重新确认。完整历史外部约束恢复、拔模和正式本地推理验证仍不在本次已通过范围内。
