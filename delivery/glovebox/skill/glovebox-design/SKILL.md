---
name: glovebox-design
description: 根据用户的手套箱把手底座建模或改参要求调用预定义 CAD 流程，在检查失败时提出参数调整并继续构建。仅支持已登记圆形草图和凸台子流程。
---

# 手套箱建模与检查失败后的决策

用户要求实际设计、构建或修改手套箱把手底座时使用。先说明本流程只覆盖历史平面、圆形草图和到平面凸台；完整手套箱、外部定位约束及 DS 合规尚未验证。一般咨询不启动 CAD。

## 从需求到一次自动构建

调用 get_workflow 获取参数、默认值、单位、流程和能力边界。将用户要求映射到 radius_mm（圆形草图半径，毫米）。直径要除以二；不要把壁厚、整体尺寸或含糊的“厚一些”擅自映射成半径。无法唯一映射时询问用户。

用户允许范围时，在范围内选择初值并保留范围约束；除非用户规定，优先选择范围内的默认值。缺少半径时允许使用已登记默认值，但最终报告必须披露。检查条件由用户或宿主固定提供，不能自行编造工程标准。开发回归阈值不等于 DS。

调用 start_build，参数示例为 {"parameters":{"radius_mm":5.0}}，使用默认值则为 {"parameters":{}}。一次调用会自动建立全部已定义特征并检查。不要再逐步提交平面、草图和凸台操作；不要重新组织 Pipeline 或修改其文件。

## 根据结果采取下一步

- passed：结束建模，报告实际参数、默认值来源、测量、规则来源及 DS 未验证的边界。成功模型保持打开供目视检查。
- check_failed：读取实测值、要求值、remaining_builds 和 attempted_parameters。只有允许修改的参数能合理影响该检查时才提出新值；保持用户范围和固定规则。提交 resume_build，执行器决定回退位置。
- needs_input：询问 required 中的缺失参数；得到答复后通过 resume_build 提供。
- execution_error：这是技术故障，不要盲目换参或宣称无解。报告错误并排查环境、引用或文件；只有确认故障解除才以空 parameter_changes 显式重试。
- rejected：依据错误修正请求。过期 revision 先 inspect_build 查询状态，不能反复发送旧请求。
- 无可行候选、预算用尽或需要牺牲用户约束：停止并解释，不能新建运行来绕开预算。

例如半径 5.0 mm 的体积不足，且用户允许 5.0–5.5 mm，可依据体积随半径平方变化估算所需半径，再选范围内的合理值；最终是否通过仍由 CAD 实测判断。不得直接把估计值称为验证结果。measurement.area_mm2 是实体表面积，不是截面积；volume_mm3 是体积。报告保留测量字段含义。

resume_build 请求示例：
{"run_id":"从结果读取","expected_revision":7,"parameter_changes":{"radius_mm":5.5}}

revision 必须取最新结果。只提交变化的设计参数，不提供 before_step、步骤列表或新检查阈值。读取返回的 recovery，核对自动失效和重跑清单；检查仍失败时继续按上述规则决策。一次正常构建通常只需要一次启动；失败时才追加决策调用。

## 只有终端时的对应方式

在交付包目录调用独立脚本。请求文件使用 UTF-8，所有命令使用同一 workspace：

python -X utf8 cad_cli.py workflow
python -X utf8 cad_cli.py start --request start.json --workspace D:/cad-runs
python -X utf8 cad_cli.py inspect --request status.json --workspace D:/cad-runs
python -X utf8 cad_cli.py resume --request resume.json --workspace D:/cad-runs

CLI start 比宿主工具多一个 policy 字段，由调用方提供 radius_min_mm、radius_max_mm、minimum_volume_mm3、check_source。inspect 请求只有 run_id；resume 与上例相同。退出码 0 为正常，2 为等待设计决策或补充输入，3 为拒绝或技术错误；始终读取 JSON 状态。工具映射为 get_workflow→workflow、start_build→start、inspect_build→inspect、resume_build→resume。

脚本不连接模型服务。Skill 由客户模型宿主解释执行；没有模型宿主时工程师也可以读取失败报告、修改参数并继续。
