---
name: steering-wheel-design
description: 使用已配置的方向盘骨架流程理解设计参数、执行CATIA建模，并在检查失败后单参数恢复；处理缺输入和阶段确认，不生成发泡工艺或宣称夹具为正式骨架。
---

# 方向盘骨架建模

使用宿主提供的固定流程。先调用get_workflow，读取可变量、单位、范围、默认值来源、阶段和检查条件。将用户要求映射到已声明参数；没有对应参数时说明缺口，不把新的设计要求转换成改检查条件。fixture_only为true表示机制夹具，必须明确告知不是实际CAS设计或DS验收。

流程中的parameter_bindings给出参数绑定的操作字段路径，parameter_effects列出直接使用步骤、受影响步骤及不受影响步骤。恢复前核对候选参数的affected_steps包含失败步骤；不依赖该参数的失败不能靠修改它解决。影响关系不说明参数增减与检查值之间的单调性，不据此猜测几何响应或保证下一次一定通过。

## 开始与继续

1. 调用start_build提交参数。可以使用流程明确给出的默认值；用户明确要求的首次值必须保留，不提前替换为更容易通过的值。start_build会自动运行到结束、检查失败、缺输入或确认节点，不逐步调用CAD。
2. 已有运行时调用inspect_build读取最新状态。后续调用只使用该运行的run_id和最新revision，不另开运行绕过尝试预算。
3. check_failed时读取失败步骤、实测值、限值及来源。若check.results包含多项结果，检查所有未通过项及已通过项的上下限，不只处理首个失败条件；单位和规则版本随项核对。依据几何关系提出一个允许范围内的新参数；用户已指定恢复候选时使用该候选。调用resume_build，一次只提交一个parameter_changes字段。执行器计算失效范围，保留无关分支；模型不指定回退步号、不编辑状态文件。
4. 不重复已经尝试的参数组合。没有依据决定下一候选、候选耗尽或预算耗尽时，报告阻塞项并停止调用，不能降低阈值或创建新运行重置预算。

## 状态分支

- needs_input：报告input_issues中的缺项，请输入方补齐。不得猜测对象、单位、坐标或文件版本。宿主按原清单补齐后使用retry_inputs；本开发模型入口不开放文件修改。
- waiting_confirmation：报告待确认步骤及报告指纹，等待真实用户确认。不要调用resume_build假装确认；不要自填confirmed_by。人工确认由宿主独立提交confirm，模型工具中不提供confirm。
- execution_error：说明失败的技术操作，保留运行信息并停止。未经修复，不将CAD异常解释为应调整设计参数的工程不合格。环境故障修复后由宿主调用CLI的retry，同一参数和代码/流程版本继续未完成步骤，仍消耗原预算；本模型工具不开放retry。
- completed：仅表示当前配置流程完成。分别报告实际通过的检查和ds_status；not_evaluated不能表述为DS通过，更不能表述为完整方向盘交付。

最终用简短中文说明采用参数、实测值、检查结果、重建/保留的阶段，以及仍需用户处理的事项。saved_cad_outputs列出的逻辑输出已由宿主核验磁盘文件和哈希，可以报告这些输出已保存；model_kept_open另行证明保持打开。二者不要混淆，也不要在已有保存证据时声称无法确认保存。没有工具证据时不宣称已构建、已保存或已保持模型打开。机制夹具及DS边界说明一次即可，不重复堆叠警告或添加无关后续服务提议。

## 工具契约

- get_workflow：无参数，读取固定流程摘要、参数字段绑定和影响范围。独立脚本宿主可用CLI的describe命令，输入JSON只含flow路径，无需启动CATIA。
- start_build：parameters为已声明设计参数的数值映射；一个宿主会话只允许一次开始。
- inspect_build：run_id。
- resume_build：run_id、expected_revision、parameter_changes。

没有模型工具的宿主可调用仓库tools/steering_cli.py的start、inspect、resume命令并读取JSON。confirm及retry_inputs供宿主在人工确认/补齐输入后单独调用，不能通过本Skill扩大操作授权。开发阶段仅在用户允许时使用公网模型；交付脚本不依赖模型SDK，正式纯本地要求保留。
