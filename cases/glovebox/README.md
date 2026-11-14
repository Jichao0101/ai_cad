# glovebox：历史案例与自动 Pipeline

handle_base/ 保留来自原工程的 969 个历史文件；完整回放仍缺 common、sketch_geometry、reconstruction、model_data 等上层模块。当前采用独立执行器验证明确支持的子流程，不声称补齐了完整历史运行器。

## 历史脚本怎样配合

| 文件 | 作用 |
|---|---|
| sequence.py | 879 步的顺序与特征 ID 清单，不是运行入口 |
| _step_loader.py | 读取每步 RECORD、DEFINITION、DEPENDENCIES、GEOMETRY 并查找处理器 |
| _handlers.py | 历史 CAD 重建、引用重绑和几何检查，依赖缺失的父包 |
| model_info.py | 模型参数、公式和导出元数据 |
| handlers.py | 容器创建等辅助操作 |
| references/、native/ | 引用数据及 CATPart 模板，保持原目录关系 |
| merge_design_intent.py、add_columns_design_input.py | 设计意图 CSV 整理工具，不是建模入口 |

离线检查仍可运行：

```powershell
.\.venv\Scripts\python.exe cases/glovebox/verify.py
```

## 当前可交付子流程

交付位于 [delivery/glovebox](../../delivery/glovebox/README.md)。真实几何依赖为平面 249、671 → 草图 701 → 到平面凸台 794。圆半径可变，圆心与坐标系冻结；原定位 OriginPt 和相合、相切约束没有恢复，拔模 795 不在该子流程内。

执行器暴露 workflow、start、inspect、resume。pipeline.json 预定义平面、草图、凸台及最终检查，start 连续执行到通过或需要决策；模型只提供初始参数或失败后的 parameter_changes。执行器根据绑定关系计算最早受影响步骤，恢复检查点并自动重跑。每次命令可在新进程执行，状态由运行目录持久化。具体 JSON 契约见交付 README 与 Skill。

旧 run_glovebox 实现及分段命令已被自动 Pipeline 接口替代。经用户明确授权，删除旧驱动、旧流程配置和旧测试；handle_base 原始代码及 runs/ 历史证据保留。当前只维护一套 CAD 操作实现。

## 开发验收与交付分离

从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe tools/verify_automatic_cli.py
.\.venv\Scripts\python.exe -X utf8 dev/qwen_acceptance.py "按Skill自动建立手套箱圆形凸台，先试半径5毫米；失败后在5至5.5毫米范围内调整半径继续，由执行器决定回退位置。" --policy dev/regression-policy.json --allow-cloud
```

第一条通过独立脚本执行完整验收，不需要 Agent 或 API Key；第二条让 Qwen 按 Skill 映射参数并处理检查失败；CAD 操作自动连续执行，每次工具调用均启动新的 CLI 进程。Qwen 的 Base URL、模型名和 Key 放在被 Git 忽略的 .env.local，仅开发程序读取，交付脚本不读取它。

回归策略中的半径范围 5–5.5 mm、最低体积 1300 mm³ 仅为测试条件，不是 DS 规范。半径 5 mm 的实测体积约 1128.915725 mm³，半径 5.5 mm 约 1365.988028 mm³。通过后仍明确 DS 未验证。

验收覆盖整条流程自动构建、默认值来源、过期版本拒绝、禁止手动指定回退点、规则不可变、自动恢复、同参干净构建、重复候选拒绝、累计预算及交付包异地解压执行。产物在 runs/，保留每次命令输入、返回状态、进程 ID、检查点和测量，不记录 Key。

## 方向盘迁移

可复用独立命令协议、预定义流程、参数绑定、状态版本、检查点和测量机制。方向盘的支撑面、操作注册、参数定义、外部约束和 DS 必须另行确定。不能将当前冻结定位或回归体积阈值直接迁移为方向盘工程标准。
