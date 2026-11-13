# glovebox：handleBase 历史回放案例

本目录的 handle_base/ 是手套箱把手底座导出包，来自 D:\console_box\AI_CAD\construct_steps-handleBase\construct_steps-handleBase。保留了原始源码、步骤 JSON、模型信息、设计意图表、引用数据和 native 模板，省略解释器缓存。案例用于研究 Python 控制 CATIA、提取命令和比较参数变体。当前可运行的入口是离线检查程序 verify.py；完整 CAD 回放仍缺原项目上层运行器。

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
