# 方向盘骨架开发验证包

这是可独立运行的开发验证包，包含CAD执行脚本、流程样例、Skill和验证程序。不是完整方向盘业务交付：CAS自动识别、平台HUB及附件、CAE加料和完整DS仍有未完成项，见package-manifest.json中的状态说明。参考件R34对照及正式本地模型部署尚未验收。

## 安装与自检

在Windows中解压到任意可写目录，确保已安装Python并启动CATIA V5。运行install.bat创建本包虚拟环境并安装requirements.txt，再运行check.bat检查包文件哈希、依赖与CATIA连接。自检不创建模型，也不会关闭现有文档。运行verify.bat会创建测试Part，执行失败后改参恢复，并保持测试结果打开。

本包不含API Key、模型SDK或开发Agent。需要模型执行时，由你的宿主加载projects/steering_wheel/skill/steering-wheel-design/SKILL.md，并映射下述CLI契约。是否需要人工确认仍以业务规则为准，模型不能代签。

## 第一次运行

在包根目录打开PowerShell。以下命令使用本包环境，首次故意以8.4mm触发夹具体积检查失败：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/steering_cli.py start examples/start-baffle.json
```

输出JSON中保存run_directory、revision、status及check。填写一个resume.json，把run_directory和expected_revision替换为刚才输出的实际值：

```json
{
  "run_directory": "实际运行目录",
  "expected_revision": 0,
  "parameter_changes": {"thickness_mm": 10}
}
```

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/steering_cli.py resume resume.json
```

执行器在同一运行改参，保留基准，只重建辐板。实测体积应为24000mm³；这只是机制夹具，不是DS验收。源文件、各次阶段资产、报告及state.json保存在runs中。

## 状态与恢复

inspect请求只含run_directory。resume请求含run_directory、最新expected_revision和一个parameter_changes，不允许重置原运行预算。检查失败、技术故障、缺输入和等待确认是不同状态；CLI进程退出0不等于工程通过，须读取status和ds_status。

技术故障修复后可调用retry，请求含run_directory和最新expected_revision。它保持参数，保留已完成阶段，仅重试未完成步骤并计入max_attempts。必须是同一代码/流程版本，且资产哈希未变；不支持以修改代码后的新行为继续旧检查点。模型不得把技术异常当作应调设计参数的检查失败。

需要确认的步骤返回waiting_confirmation及pending_confirmation。人工认可报告后，宿主调用confirm，请求包括run_directory、最新expected_revision、报告fingerprint和真实confirmed_by。它不是身份认证服务。缺初始输入时返回needs_input；按固定清单补齐后使用retry_inputs，请求包括run_directory和expected_revision。不要修改state.json绕过任何检查。

## 验证范围

本次源码包包含基准/辐板、原生引导线裁剪与圆/矩形扫掠、显式截面和圆截面端部桥接、辐条/镜像/布尔组合、直边圆角、原生对时角度及间隙恢复、多项检查、STEP实体数量检查、Publication与开发移交。具体操作和参数见projects/steering_wheel/README.md，阶段缺口见同目录STATUS.md。IMPLEMENTATION.md保留仓库实施记录，其中引用的历史runs证据未打入本包；验证脚本会在本包内生成新证据。

开发Qwen宿主只作为仓库联调说明，不随包提供。所有续跑入口均要求代码和固定流程版本一致，升级包后不能隐式复用旧检查点。

可在包根目录运行以下验证，每项使用自身的runs子目录：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_checks.py
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_symmetry.py
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_subtract.py
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_endpoint_bridge.py
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_solid_domains.py
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_fillet.py
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_clocking.py
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_steering_*.py'
```

多项检查报告记录各项单位、上下限、来源和版本，改参后保留旧报告。四点检查不能代表整面CAS对称；减料夹具不能代替真实环境槽位规则。工程检查值来自配置，不由Skill随意更改。

端部桥接验证会组合两个扫掠段及桥接体，再检查STEP实体数量；带空腔的一个实体可以包含两个封闭壳，因此实体数量与壳数量分别报告。对时验证除CLI恢复外，还会在另存副本中直接修改原生角度并核对组合件内几何响应。STEP检查不等同原生拓扑或完整DS验收。

verify.bat执行基准/辐板恢复。需要观察轮圈、辐条和镜像组合时，运行虚拟环境Python执行tools/verify_steering_skeleton.py；它另存VisibleSkeletonFixture.CATPart并保持打开。其他verify_steering_*.py按名称验证管柱轴线、平面/曲面投影、间隙、外部输入、确认和局部恢复。

圆截面Loft与样条扫掠的严格解析体积对照仍有未解决误差，verify_steering_sections.py和verify_steering_spline.py会明确报告失败，不能将这些脚本当作全部应为绿色的发布测试。成功创建或保存不证明工程规则全部通过。原型只在当前V5客户端测试，不能据此声明V6、R34、VDI或实际方向盘样件通过。

升级采用新目录，保留旧包及其runs；package-manifest.json记录包内文件哈希，便于确认使用的是哪个版本。
