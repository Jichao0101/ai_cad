# 手套箱预定义 Pipeline 交付包

本包交付独立 Python 执行脚本、Skill、流程配置和必要历史资产。执行器连续执行预定义流程，模型仅负责需求映射和检查失败后的设计决策。包内不含 Agent、Qwen 驱动、模型 SDK 或凭据。

## 安装和职责

需要 Windows、CATIA V5 和可访问 COM 的 Python。当前验证环境为 V5-6R2022、Python 3.13、pywin32 312。

```powershell
python -m pip install -r requirements.txt
python -X utf8 cad_cli.py workflow
```

| 文件 | 职责 |
|---|---|
| pipeline.json | 流程版本、四个操作、对象依赖、参数绑定和检查点后的检查 |
| cad_cli.py | 独立进程的 JSON 命令入口 |
| automatic.py | 自动推进、参数来源、决策暂停、计算回退与重跑范围 |
| executor.py | 状态版本、运行锁、快照、操作执行、检查和恢复 |
| operations.py | CATIA 平面、草图、凸台与真实测量 |
| assets/ | 历史步骤 249、671、701、794 和 SHA-256 清单 |
| skill/glovebox-design/SKILL.md | 模型的需求映射、结果判读和异常决策指引 |

## 命令和请求

每次调用可以启动新 Python 进程。请求文件采用 UTF-8，运行目录必须保持一致。

```powershell
python -X utf8 cad_cli.py start --request start.json --workspace D:/cad-runs
python -X utf8 cad_cli.py inspect --request status.json --workspace D:/cad-runs
python -X utf8 cad_cli.py resume --request resume.json --workspace D:/cad-runs
```

start.json 的开发回归示例：

```json
{"policy":{"radius_min_mm":5.0,"radius_max_mm":5.5,"minimum_volume_mm3":1300,"check_source":"development regression fixture; not DS"},"parameters":{"radius_mm":5.0}}
```

1300 mm³ 只用于制造可复现检查失败，不是项目 DS。省略半径时传 parameters={}，使用 5.5 mm 默认值并记录来源；默认值也必须落在 policy 范围内。

status.json 为 {"run_id":"实际返回的运行编号"}。继续请求为 {"run_id":"实际编号","expected_revision":实际版本号,"parameter_changes":{"radius_mm":5.5}}。使用最新返回的整数 revision；恢复位置和检查阈值不属于继续请求。

workflow 返回流程定义；start 自动完成平面→草图→凸台→保存重开测量；inspect 只查询持久化状态；resume 计算最早受影响步骤、恢复检查点并自动重跑。退出码 0 为正常，2 为 check_failed 或 needs_input，3 为 rejected 或 execution_error。

## 恢复与运行记录

半径绑定到 profile 步骤，pad 引用其圆形草图。改半径时自动恢复到 profile 之前，保留两张支撑面，重新创建 profile 和 pad。恢复结果包含依赖影响、实际失效、重跑以及快照连带移除的步骤清单。整份快照恢复可能需要重建依赖之外的后续步骤，不能仅以依赖列表推断仍然有效。

每个成功操作提交独立 CATPart 检查点和状态。技术失败保留最后已提交步骤，修复原因后可以空参数变化继续；工程检查失败必须提供新参数。禁止重复尝试已测参数组合，最多四次成功创建的实体候选，恢复不重置预算。过期版本、越界、修改固定规则和已完成运行的继续请求均拒绝。

运行目录保存 state.json、snapshots/、events/；COM 指针不跨进程保存。脚本、Pipeline 或资产变更后应新建运行。人工未保存修改会使相关模型操作停止。成功模型保持打开并调整视图，供工程师目视验证。

## 适用边界和迁移

当前仅覆盖把手底座的限定子流程。平面使用历史求值方程，草图圆心与坐标系冻结，仅半径可变；外部约束、拔模 795、完整 879 步、3DE R2022x 和正式 DS 尚未验证。

迁移方向盘时先从工程师操作提取可靠前置引用、可变参数和检查依据，再添加确定性 CAD 操作及 Pipeline 参数绑定。不要将本例最小体积或冻结坐标当作方向盘规范。当前配置格式只实现本例所需操作和最终检查，不是通用工程工作流平台。

客户宿主将命令映射为 get_workflow、start_build、inspect_build、resume_build，加载 Skill 后调用。宿主为 start 注入固定 policy。没有模型时工程师也能用相同命令完成恢复。开发用 dev/qwen_acceptance.py 留在仓库外层，不属于本交付包；正式本地推理仍由客户宿主提供。
