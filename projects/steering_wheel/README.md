# 方向盘骨架工具

完整阶段的实现与缺口核对见[STATUS.md](STATUS.md)。独立开发验证包由`python -X utf8 tools/build_steering_package.py`生成，采用白名单收录脚本、Skill、参数夹具和验证程序，包含安装、自检与验证BAT；不会打包开发Agent、API Key或原始业务资产。

当前已接入执行器的阶段为基准求解、圆形/凸多边形辐板、圆弧段、显式点列样条段、三矩形截面辐条连接体及原生Body布尔组合。样条段已验证创建和位置持久化，解析体积对照尚未通过。完整骨架的CAS曲线适配、轮圈桥接、辐条环境适配、平台附件及CAE加料仍在开发；参考零件对比按用户安排待升级CATIA后进行。

## 完整集成演示

在仓库根目录打开终端，先启动CATIA，再执行一个命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools/verify_steering_integrated.py
```

该入口经独立CLI进程读取`tests/fixtures/steering_integrated_flow.json`，构建基准、辐板、轮圈、辐条及组合骨架。首次轮圈半径为5mm，组合体积不满足夹具条件时，同一运行改为5.5mm；执行器重建轮圈、组合及后续检查，保留基准、辐板和辐条。固定体积条件为100000～110000mm³，用于验证恢复机制，并非客户DS。

恢复通过后，流程执行STEP单实体检查、创建实体和基准轴系Publication并整理显隐。入口另做一次同参干净构建对照，导出开发移交包，再打开移交包中的CATPart核对体积、发布引用及显隐，最终保持该模型打开。整个演示不调用模型API；它验证Skill和模型宿主共用的CLI执行链。

结果位于`runs/steering-integrated-时间戳/`：`result.json`记录汇总，`start.json`和`resume.json`保留实际请求，`handover/`包含最终CATPart、STEP、基准和检查报告。目录中的请求绑定当次运行及revision，查看请求可理解调用方式，不要直接重放已经过期的resume。

模型参与时，使用已配置开发API的宿主执行同一份流程：

```powershell
$requirement = "使用方向盘骨架Skill，首次轮圈截面半径5毫米；组合体积检查失败后改为5.5毫米，继续同一运行，不修改检查条件。完成STEP检查和发布引用，中文报告测量、保存结果和DS状态，保持模型打开。"
.\.venv\Scripts\python.exe -X utf8 dev/qwen_steering_acceptance.py $requirement --flow tests/fixtures/steering_integrated_flow.json --allow-cloud --keep-open
```

Qwen入口保存会话和运行至`runs/qwen-steering-时间戳/`，模型只负责参数和恢复决策，工序仍由执行器推进。该入口会打开成功阶段模型；独立集成验证入口还会执行干净构建对照及移交包导出，两者的验收范围不同。无需在正常模型建模时重复执行干净构建。

这是合成骨架工序集成，尚不包含真实CAS选面、HUB/附件库、CAE加料和完整业务DS。无需为了使用此演示逐个运行下列专项验证。

## 专项回归验证

在仓库根目录、CATIA已启动时执行：

```powershell
python -X utf8 tools/verify_steering_runtime.py
python -X utf8 tools/verify_steering_retry.py
python -X utf8 tools/verify_steering_round_baffle.py
python -X utf8 tools/verify_steering_circular_profile.py
python -X utf8 tools/verify_steering_column_axis.py
python -X utf8 tools/verify_steering_plane_surface.py
python -X utf8 tools/verify_steering_symmetry.py
python -X utf8 tools/verify_steering_native_guide.py
python -X utf8 tools/verify_steering_surface_projection.py
python -X utf8 tools/verify_steering_branches.py
python -X utf8 tools/verify_steering_combine.py
python -X utf8 tools/verify_steering_spoke.py
python -X utf8 tools/verify_steering_curved_spoke.py
python -X utf8 tools/verify_steering_mirror.py
python -X utf8 tools/verify_steering_skeleton.py
python -X utf8 tools/verify_steering_confirmation.py
python -X utf8 tools/verify_steering_inputs.py
python -X utf8 tools/verify_steering_clearance.py
python -m unittest discover -s tests -p 'test_steering_*.py'
```

第一个命令验证基准与辐板的跨进程恢复；第二个命令验证轮圈失败后改参，仅重建轮圈，保留基准和辐板，并与同参从头构建对照。测试尺寸和体积条件是机制夹具，不是实际方向盘参数或DS限值。日志与阶段CATPart保存在runs。

## 文件职责

| 文件 | 职责 |
|---|---|
| datum.py | 根据明确的原点规则求轴系，并创建原生轴系 |
| column_axis.py | 在具名范围内识别唯一圆柱面，读取管柱轴线与半径 |
| plane_surface.py | 读取具名平面及法向，并校核底罩投影点位于实际面片上 |
| symmetry_points.py | 读取两组配对CAS点，构建共同中分面并核对四点镜像关系 |
| native_guide.py | 裁剪外部具名开放曲线，建立法向圆/矩形截面及原生Rib |
| surface_guide.py | 按显式基准平面与曲面求交，保存原生引导线及对象路径 |
| surface_projection.py | 原生曲面求交，按实际面片和指定区间校核唯一投影点 |
| baffle.py | 从圆或凸多边形与支撑坐标创建原生草图和厚度Pad |
| circular_profile.py | 底罩面截取闭合圆、明确轴向平面偏置及径向内缩 |
| sections.py | 圆截面、原生Rib和带明确闭合点的Loft操作 |
| rim_segment.py | 将圆弧引导与截面组合成轮圈段 |
| spline_segment.py | 从显式局部点列和起始截面生成原生样条扫掠 |
| rim_bridge.py | 从两个显式圆/矩形端部截面生成原生Loft桥接体，支持流程改参恢复 |
| solid_domains.py | 隔离主Body并导出STEP，统计显式实体数量并保留证据；不等同原生连续性检查 |
| edge_fillet.py | 以显式全局端点唯一匹配主Body直边，创建可编辑的最小传播圆角 |
| combine.py | 复制阶段原生Body和支撑，布尔添加到最终Part |
| spoke.py | 根据三个显式矩形截面，以直线或样条边界构建两段Loft连接体 |
| mirror.py | 在指定阶段副本中按基准对称面执行原生Body镜像 |
| inputs.py | 外部CATPart清单、哈希和逐层具名对象校核；运行副本隔离 |
| clearance.py | 原生最小间隙、最近点与被测对象记录，支持具名曲面引用 |
| cad_frame.py | 草图轴系浮点数组封送及读回核验 |
| flow.py | 解析参数绑定、对象依赖及分支失效范围 |
| runtime.py | 状态、运行锁、阶段资产、检查和改参继续 |
| ../../tools/steering_cli.py | 独立JSON命令行入口，无模型API调用 |

## 命令契约

运行`python -X utf8 tools/steering_cli.py <命令> <请求JSON文件>`。

- `start`：请求含`flow`配置路径、`runs_root`输出根目录及`parameters`。
- `inspect`：请求含`run_directory`，读取当前状态。
- `resume`：请求含`run_directory`、最新`expected_revision`及只包含一个参数的`parameter_changes`。
- `confirm`：请求含`run_directory`、最新`expected_revision`、待确认报告的`fingerprint`及`confirmed_by`。由宿主在取得人工确认后调用。
- `retry_inputs`：请求含`run_directory`和最新`expected_revision`；补齐固定输入清单中的文件后，在同一运行重试加载，不重置尝试预算。
- `retry`：请求含`run_directory`和最新`expected_revision`；技术故障修复后，同参执行未完成步骤，保留已完成分支，计入原运行的max_attempts。

步骤完成和检查通过分别记录。返回`check_failed`时可以提交新参数；`execution_error`表示技术故障。不要以CLI进程退出成功代替检查`status`。`completed`仅代表配置中登记的阶段执行完毕，DS状态仍单独报告。

技术retry只接受execution_error，要求执行代码和流程签名不变，且已有资产哈希一致；它适用于修复环境或连接后继续，不是代码版本迁移入口。旧检查点没有签名也不能直接技术重试。失败原因和重试事件均保留，预算耗尽后拒绝继续；不会通过重试创建新运行。开发Qwen工具没有开放retry，需由宿主确认故障已修复后调用。

流程步骤设置`requires_confirmation: true`时，通过已配置检查后进入`waiting_confirmation`。读取`pending_confirmation.report`向用户展示该阶段的参数、规则、测量和文件版本，用户认可后提交同一报告指纹；检查失败时不能通过确认跳过。改参会移除受影响步骤的有效确认并保留失效事件，无关分支的确认继续有效。确认不增加参数尝试次数，也不重置原有预算。报告、参数规格或阶段资产变化后拒绝旧确认。

确认接口实现的是状态与证据绑定，`confirmed_by`只记录来源，不具备身份认证能力；正式宿主负责识别实际确认人。模型不能自行填写该字段冒充用户批准。回归脚本使用`AUTOMATED FIXTURE ONLY`验证协议，不构成业务签认，也没有解决SOR无人干预与人工确认的业务冲突。

目前每个分支独立保存原生文件；保留分支直接复用原资产与哈希，不从整件旧快照覆盖它。combine步骤的inputs将角色名映射到阶段输出，parameters为空对象；可额外用保留角色`basis`传入B10基准JSON，在最终Part中生成原生B10_DesignAxis，其他角色仍指定至少两个待组合Part。组合复制原生历史及支撑，最终Part中可继续编辑原Pad；上游资产变动后由执行器重建组合，不建立跨文件实时链接。已有相交Pad及混合Pad/Rib/Loft夹具验证，尚不证明真实复杂轮圈、附件的复制完整性或整骨架连通性。

baffle操作接收basis输入及thickness_mm；轮廓二选一：outline为局部凸多边形顶点，radius_mm为以基准原点为中心的圆半径。两者不能同时提供。圆分支输出还会读回原生草图半径，保存后可编辑B20_Circle和B20_Thickness。此操作接收已确定轮廓；底罩求交使用下一段的前置操作，不自行决定六/八边形分支。

圆形底罩可先用circular_profile操作：inputs为source外部Part和basis，parameters中的surface_binding选择面，plane_offset_mm指定沿基准Z轴的轮廓平面偏置（缺省0），radial_inset_mm指定截线半径的内缩量。二者不是同一个参数，不自动套用发泡/塑料配置规则。相交必须得到一个完整圆，半径大于内缩量；输出采用实测圆心，允许其偏离设计轴原点。随后baffle使用profile输入消费该输出，仅设置thickness_mm，不再同时指定outline或radius_mm。非圆拟合仍不支持。

column_axis操作的source输入指向外部管柱Part，scope_binding指定输入清单中已核对的Body/特征范围，positive_direction明确车辆方向参照。范围内必须只有一个圆柱面；多面不自动选第一个，正向参照与轴垂直也不猜测。输出包含轴上一点、单位方向、半径及源文件/面引用。datum步骤可用column输入消费该输出，此时不再同时填写column_point和column_direction。对称面可来自明确平面输入或下述四点构造，底罩投影仍使用明确输入。

symmetry_points操作使用外部source和point_pairs，例如`[["left_a","right_a"],["left_b","right_b"]]`；四个名字分别绑定输入清单中的具名点，positive_normal确定法向正向。第一对点建立垂直平分面，第二对点核对是否与同一平面镜像相容；两组中点必须不同，配对点不能重合。输出point_mm、normal、四点位置、中点、逐对镜像偏差及输入引用，可由datum的symmetry输入直接消费。此时不再同时填写symmetry_point/symmetry_normal。

四点共同平面采用1e-6mm数值一致性容差，不对不对称点做最佳拟合，不自动寻找点或调整配对。真实CAS特征点选择和整张曲面的镜像偏差检查仍待业务输入及实样验证；四点通过不能代表整个CAS通过对称性检查。

plane_surface操作接收外部source、surface_binding及positive_normal，读取明确的平面面片，不拟合非平面几何。datum的bottom/symmetry输入可消费对应输出，此时移除同名角色的point/normal显式参数。底罩原点求交后还测量到实际面片的距离，超过1e-6mm的数值一致性容差即拒绝，避免将面片之外的平面延伸当作有效投影。该容差不是DS限值。辅助测量点仅在内存中创建，输入副本关闭时不保存。

非平面底罩使用datum的bottom_surface输入，指向外部Part；参数bottom_surface_binding指定具名曲面，projection_extent_mm明确沿管柱方向在种子点两侧搜索的长度。不能同时配置平面bottom或bottom_point/bottom_normal。执行器创建原生相交，保留候选后按原面片和有限线段区间校核，只有一个有效点时继续；零个或多个有效点均停止，不默认选最近点。1e-6mm用于几何一致性及重合候选去重。当前半圆柱/整圆柱夹具已验证，复杂自由曲面、切触退化及四点基准与真实CAS投影的组合仍待实样验证。

spoke操作接收basis输入，parameters中包含thickness_mm和三个sections。每个截面明确提供局部center_mm、单位方向x/y及width_mm；厚度围绕截面中心对称分布，上下各thickness_mm/2。默认连接使用对应角点之间的直线引导。提供guide_bends_mm时，用两个局部三维偏移向量分别控制两段连接的样条中间点，端点由截面角点确定，中点采用PointBetween加相对偏移，端部切向沿截面法向并按前进方向定向。guide_length_mm是八条边界引导线的长度总和，不是辐条中心线长度。

直边与样条方案均属显式定位截面原型。开关包络选型、定位实体①②③、环境挖槽、实际造型规则与工程连续性检查尚未全部实现，不能将该原型当作B50/B60工程验收完成。

mirror操作的inputs必须提供basis和source，结果包含原阶段及其镜像。source应指向需要镜像的独立轮圈或辐条资产，不能指向包含非对称平台结构的整件。执行器先复制文件再修改，原资产保留；镜像范围由流程的依赖绑定明确指定。

`tests/fixtures/steering_skeleton_flow.json`是辐板、圆轮圈、双侧辐条组合夹具，使用合成尺寸验证原生Pad/Rib/Loft/Mirror混合复制和恢复。运行verify_steering_skeleton.py会另存隐藏辅助几何的VisibleSkeletonFixture.CATPart并保持打开。它不包含真实CAS、HUB、固定附件、CAE加料或DS检查，不能用于实际方向盘发布。

## 外部输入清单

流程的external_objects将逻辑ID映射到CATPart清单。下例的platform可作为后续步骤inputs中的对象ID；path、sha256和对象名称须填写实际值。

```json
{
  "external_objects": {
    "platform": {
      "path": "D:/input/platform.CATPart",
      "sha256": "填写实际文件的64位小写SHA256",
      "unit": "mm",
      "coordinate_system": "design_global",
      "objects": {
        "body": [{"collection": "Bodies", "name": "PlatformBody"}]
      }
    }
  }
}
```

加载先检查清单与文件哈希，再打开运行副本逐层核对objects。每层名称必须唯一；重名、缺对象或CATIA无法打开文件均返回needs_input及input_issues，不开始后续建模。objects是必需对象的核对清单；combine仍复制输入Part的主Body，不按某个绑定挑选子Body。BRep面、装配变换和自动CAS特征识别尚未接入。

unit与coordinate_system是输入方声明，目前支持mm及design_global/part_local；代码没有自动证明来源坐标或尺寸标定正确。part_local输入只能作为place步骤的source，不能未经定位直接用于组合、间隙或其他操作。原件不会被保存修改，流程使用记录哈希的副本。retry_inputs只补齐当前清单，不能用改参调用绕过缺项，也不允许静默替换为其他版本的模型。已加载输入的版本替换和依赖确认失效还需专门的输入更新协议。

## 几何间隙检查

clearance步骤的inputs指定first、second两个阶段对象。默认测量各Part主Body的末端实体特征；外部CAS曲面可通过parameters的first_binding或second_binding指定输入清单objects中的绑定名。它直接调用CATIA最小距离并读回最近点，结果写入JSON，附带两个输入文件的版本记录。

检查使用既有check配置，measurement填写minimum_distance_mm，minimum和source填写经确认的限值及来源。检查失败后模型只能改设计参数，执行器据依赖重建几何及检查。体积条件和间隙条件各自记录，不能互相代替。

当前验证覆盖分离、相交/包含实体及平面曲面，单位为mm。最近点附带特征或具名曲面路径，尚不提供具体BRep面ID；零距离不能区分接触与穿透深度。这也不是CAS包覆余量、曲面法向或完整DS检查的替代品，复杂曲面仍须实样验证。

## 外部原生轮圈引导线

`native_guide`操作的`source`输入使用外部Part清单，`guide_binding`选择具名开放曲线，`section_radius_mm`为圆截面半径。执行器复制整个输入Part到阶段资产，读取原生曲线起点，建立法向平面及截面，在新Body中生成Rib并将其设为主Body。原有输入几何保留为支撑，原文件不修改；后续组合只消费新的主Body。

若引导线来自曲面，先使用`surface_guide`：输入为清单中的`source`曲面Part及`basis`基准，参数`surface_binding`选择已声明曲面，`plane_offset_mm`控制沿基准Z轴的求交平面偏移。输出Part保留原生平面和交线，测量结果给出`guide_path`及曲线起点/中间点/终点。后续`native_guide`可消费此Part，使用`guide_path`对象路径替代外部清单的`guide_binding`；两者必须二选一。

当前生成路径为`[{"collection":"HybridBodies","name":"B40_SurfaceGuide"},{"collection":"HybridShapes","name":"GuideIntersection"}]`。求交关闭延伸，验证曲线长度、开口及采样点所在平面；无交线或闭合交线停止。多分支选择、闭合曲线分段和真实CAS的6/9/12点映射仍需明确规则，不能根据输入造型顺序猜测交线方向。运行`tools/verify_steering_surface_guide.py`可验证合成曲面偏移0→5mm、间隙3→8mm的局部恢复，以及无交线/闭合交线拒绝。

按比例分段前，可在`surface_guide.parameters`指定`start_hint_mm`全局参照点，例如`[0,0,0]`。距参照点较近的端点作为起点；两端等距时停止。需要反向时建立原生Inverse特征并读回端点、长度，后续百分比裁剪使用这个真实反向后的曲线，不只是交换报告中的端点。逻辑路径仍为GuideIntersection，原始交线保留为GuideIntersectionRaw。未指定参照点时保留CATIA方向，不自动赋予6/9/12业务含义。

矩形截面改用`rectangle`对象，包含`width_mm`、`thickness_mm`和全局坐标中的`thickness_direction`，不能同时指定圆半径。方向投影到起点法向平面后确定厚度轴，宽度轴与其正交；方向平行于曲线切向时拒绝。截面以曲线起点为中心，厚度两侧各取一半，半厚由总厚度派生。该方向只定义起始截面，后续沿曲线采用现有KeepAngle扫掠，不承诺恒定全局朝向或自动分缝下移。

可设置`start_fraction`和`end_fraction`裁剪开放曲线，满足`0 <= start_fraction < end_fraction <= 1`，缺省0和1表示完整曲线。两个比例始终基于原曲线，依次保留起点之后、终点之前的原生Split，读回端点校核后再建立法向截面。输出原长度、裁剪长度及比例，比例可绑定流程可变量；20%到80%不是先剪20%后再取剩余部分的80%。

该操作尚未自动从CAS面提取轮圈线，业务分支应采用哪些比例仍需明确配置。多曲线容器、闭合线或无法建立唯一法向的退化输入不自动猜测。曲线长度和预期圆管体积随实测体积输出，预期值不作为隐含验收限值；当前样条仍有严格解析体积差异。

`tools/verify_steering_native_guide.py`验证外部直线、样条输入、半径改参、原件保留和直线扫掠保存重开；`tools/verify_steering_guide_trim.py`验证比例裁剪及终点比例恢复；`tools/verify_steering_rectangle_guide.py`验证矩形厚度、方向、原生角点和干净构建对照。圆/矩形都是通用截面，不等于客户标准截面库已经接入。此源码功能新增于v2打包之后，现有v2 ZIP不含此操作。

## 多项检查与报告

严格体积差异可使用`tools/investigate_steering_volume.py <CATPart> --expected-volume-mm3 <解析参考值>`诊断。脚本在唯一命名副本中比较SPA主Body体积和指定密度的Product Inertia推算体积，逐阶段记录进度并保留源哈希。两者测量范围不同，只有核对Body范围后才可解释差值。当前单Body直线、Loft、样条夹具中两接口一致，后两者的严格解析差异仍存在，切换接口不能视为修复。

`rim_bridge`把桥接接入固定流程。它消费`basis`，参数为`section_kind`（`rectangle`或`circle`）和两个有序`sections`。每个截面提供基准局部坐标`center_mm`、单位正交方向`x/y`；矩形另给`width_mm/thickness_mm`，圆另给`radius_mm`。这些数值字段可使用现有`{"parameter":"参数名"}`绑定。两个截面的法向均须朝向第一截面到第二截面的前进方向，不能以隐式翻转猜测配对。矩形对应四角、圆截面对应正x方向闭合点，以直线引导生成原生Loft。

运行`python -X utf8 tools/verify_steering_bridge.py`可验证矩形厚度5→6mm、体积4000→4800mm³的固定检查失败恢复，保留基准/辐板，并对照干净构建和保存重开。此阶段使用明确给定的截面，不会自动读取真实CAS或扫掠端部；切向连续、真实12↔9/6↔9配对及整轮圈连通仍待验证。脚本单独报告圆Loft的严格解析误差，不能把机制恢复通过解释为该精度检查通过。

圆截面`native_guide`现在另输出`end_sections`：从裁剪后原生引导线读回起止点和法向平面，以邻近点判定沿线方向，半径沿用已建立的恒定圆截面。输出前逐一匹配扫掠主Body的实际平面端面，核对面积重心、法向及圆面积，每端须对应一个不同端面；不匹配则停止。它仍描述经实体端面交叉校验的构造截面，不是完整轮廓反求或连接连续性证明。矩形扫掠暂不输出这一数据，避免把起点厚度方向错误当成沿任意空间曲线的实际末端转角。

桥接消费这些端部时，`inputs`同时指定`basis`、`first`和`second`，后两者为相应`native_guide`输出；`parameters`只写`{"endpoints":{"first":"end","second":"start"}}`。执行器将选中端部的全局坐标转入基准局部坐标，并采用各自上游半径；不能同时覆盖截面或尺寸。上游参数变化经依赖图使桥接失效。`tools/verify_steering_endpoint_bridge.py`验证单侧半径改参后重建该侧扫掠、桥接及下游组合检查，另一侧与输入文件保持。

组合后可添加`solid_domains`步骤：`inputs`使用`{"source":"组合输出ID"}`，`parameters`为空对象，输出为受执行器哈希跟踪的`.stp`证据文件。操作将最终主Body无链接复制到临时Part，先核对复制前后体积，再导出STEP；源CATPart不保存，辅助Body不参与。可对`step_solid_count`设置来源明确的数量检查，例如夹具要求minimum=maximum=1、unit=`count`。`step_closed_shell_count`另行报告：一个带空腔实体可以有两个封闭壳，不能用壳数量替代实体数量。

这项检查依据导出文件的显式BRep实体。遇到映射实例、隐式布尔实体或开放曲面表示时拒绝计数；不以实体编号文字或注释计数，也不把空返回值解释为通过。结果受STEP转换影响，不是原生拓扑证明，不代替切向连续、制造性或完整DS检查。证据文件随开发移交包复制，保留导出器信息和文件哈希。`tools/verify_steering_solid_domains.py`覆盖分离→贴面恢复、空腔及辅助Body隔离；端部桥接验证脚本现在也检查组合后的STEP实体数量。

`edge_fillet`用于显式直边圆角，消费`source`阶段Part，在副本中操作。参数示例为`{"radius_mm":{"parameter":"round_radius_mm"},"edge_endpoints_mm":[[0,0,0],[0,0,20]]}`；端点为该Part的设计全局毫米坐标。按两端点和直线长度匹配主Body中的唯一边，允许端点顺序反向；找不到或有多个匹配都停止，不采用边序号选取。默认使用最小传播，只处理显式边。坐标匹配的1e-6mm数值容差不是DS间隙或制造容差。

输出包括原生圆角半径、特征名称、选中边、体积和`removed_volume_mm3`（输入减输出，凹边圆角可能为负）。上游拓扑变化后重新匹配；端点位置已变化时应更新明确的设计绑定，不沿用旧BRep名称猜测。`tools/verify_steering_fillet.py`覆盖半径1→2mm的检查失败恢复、原生改参、保存重开、干净构建及缺边拒绝。CAE分区、冻结区许可和制造圆角规则仍须由业务输入决定，本操作不自动选择需要光顺的区域。

同一运行的`resume`、`retry`、`retry_inputs`和`confirm`均校验启动时的执行代码与流程指纹。修改检查规则、参数范围、预算、后续步骤或代码后，不能直接沿用旧检查点；旧无指纹检查点同样拒绝继续。正常参数值通过`resume`提交，不改固定流程。该校验用于发现版本不一致，不是对有权修改全部本地文件者的防篡改认证；跨版本迁移尚未实现。

同一步可配置`checks`列表，每项填写唯一`id`、`measurement`、`unit`、`source`、`version`，以及`minimum`和/或`maximum`。上下限包含边界值，所有项目均通过才继续；单位应与测量字段一致，执行器不进行单位换算。旧单项`check`仍支持，但不能与`checks`混用。这里记录的是已配置规则的版本，不代表规则已获DS适用性批准。

例如辐板可同时检查`thickness_mm`的范围和`volume_mm3`的范围。失败时返回`check.results`中全部逐项结果，模型必须同时考虑已通过项与失败项，不能只增大参数解决下限而忽略上限。缺失、非数值或非有限测量属于`execution_error`，不应通过工程改参掩盖。

每个阶段报告保存为运行目录下的`checks-<步骤>-<指纹>.json`，记录输出资产版本、逐项实测值、规则和结果；`state.json`的`check_reports`指向当前报告。改参后保留旧报告和事件，新报告绑定新资产。确认报告也包含逐项结果。运行`python -X utf8 tools/verify_steering_checks.py`可复现厚度和体积同时失败、改参后同时通过的夹具；`ds_status`仍保持`not_evaluated`，完整DS适用项清单及正式发布门禁尚待实现。

## 原生环境减料

环境件挖槽使用`subtract`步骤，`inputs`必须含`stock`（待减料实体）和`tool`（工具实体）两个资产。执行器按此角色顺序复制原生特征并执行Remove，不依赖JSON字段顺序。输出最终体积、表面积、原件体积和`removed_volume_mm3`；可对去除体积配置既有check，再由工具尺寸的参数依赖触发局部重建。工具体的位置、形状和尺寸由上游步骤或明确输入提供。

运行`python -X utf8 tools/verify_steering_subtract.py`可在CATIA中验证检查失败、深度改参、同一运行恢复、保存重开及原生工具体编辑。最终打开的是另存的编辑演示件，跟踪中的阶段资产保持原有哈希。此夹具验证减料机制，实际方向盘环境槽位规则仍需业务输入。

## 平台件刚体定位

`placement.py`目前提供独立原生操作：输入源/目标两套右手正交轴系，将主Body通过AxisToAxis特征定位到目标位置，检查体积保持及重心变换。源轴系与目标轴系保留在Part中，可重开后直接修改目标轴系更新几何。运行`python -X utf8 tools/verify_steering_placement.py`验证平移、90°旋转、重开和改参。

流程使用`place`操作，source为待定位Part，parameters.source_frame指定其源轴系；目标可由basis输入提供B10基准，或由parameters.target_frame明确给出，两者不能同时提供。轴系包含origin_mm、x、y、z；source_frame按输入Part的当前坐标表达，target_frame按目标设计全局坐标表达。target_frame的原点等数值可绑定已声明参数，失败后由执行器重建place及下游分支。

对时可增加`parameters.clocking_deg`，例如`{"parameter":"hub_clocking_deg"}`；未提供时保留普通轴系定位，相当于0°。显式提供角度（包括0）时创建原生Angle参数，由两条公式驱动X/Y方向线旋转，目标原点和Z轴保持，正角度按目标自身Z轴的右手方向。它不改写输入B10基准。输出`clocking_parameter`给出可编辑的原生参数名；在另存副本中改角度并更新Part，几何会自动重算，不必再次调用Python。

组合复制时，顶层直接参数显式复制并加`Stage_<角色>_`前缀，名称记录在组合输出的`copied_parameters`中；轴系与方向线的公式依赖一同保留。运行`tools/verify_steering_clocking.py`可验证0→90°导致间隙20→30mm、局部恢复及保存重开，还会直接将独立Part和组合件内的原生角度改为45°核对重心。夹具角度与间隙限值不是HUB对时或DS默认值；嵌套参数集及任意客户复杂关系树尚未由本测试覆盖。

combine/subtract现在同时复制各源Part的轴系，名称加Stage_<角色>_前缀，与组合件自身B10_DesignAxis区分；原生定位特征的轴系引用随历史保留。运行`tools/verify_steering_placement_flow.py`验证局部库件定位、组合、检查失败恢复和组合件内原生轴系改参。当前只变换主实体Body，独立CAS曲面和其他Body并未变换，不能把整个输入Part的所有对象当作已转换到目标坐标。HUB自动选型和装配约束求解仍未实现。

## 给后续工序发布具名引用

`publish_references`操作复制`source`阶段Part，按`parameters.publications`映射创建真实CATIA Publication。例如`SkeletonSolid`可绑定`[{"collection":"Bodies","name":"B20_Baffle"}]`，`DesignAxis`绑定`[{"collection":"AxisSystems","name":"B10_DesignAxis"}]`。对象必须已存在，逐层名称必须唯一，已有同名Publication不覆盖；输出记录发布名称、对象路径和CATIA引用。

该操作使用Product上下文引用，直接传Part引用的方式在本机失败。保存重开后可通过Publication测量实体或取得轴系；源模型参数变化时，执行器重建后续发布步骤。它只发布明确已有对象；最终组合件应在combine阶段显式传入basis以建立待移交轴系，发布本身不补建。Publication不表示通过完整DS或获得工程发布批准。

成品展示时，在该步骤的`parameters`中显式设置`"prepare_display": true`：发布副本会显示主Body，隐藏轴系、几何图形集、主Body草图、原点平面及其他Body，并聚焦当前模型。辅助对象保留在特征树中，显隐随副本保存；源阶段资产不改动。默认不整理显隐，方便单独发布曲面或构造引用。开发宿主的`--keep-open`另行控制成功模型是否留在CATIA中。

运行`tools/verify_steering_publications.py`验证辐板实体/轴系发布和错误目标拒绝；运行`tools/verify_steering_skeleton_publications.py`验证带非零原点的组合骨架、轮圈分支改参、发布引用读回及干净构建对照。后者仍是合成骨架夹具，真实移交集还需绑定CAE状态、冻结区及完整DS报告。

## 导出开发阶段模型移交包

CLI的`handover`接收run_directory、expected_revision、asset_id和destination，目标目录必须是运行目录之外的新目录。例如asset_id可指定最终发布阶段的published_skeleton。调用方式为`python -X utf8 tools/steering_cli.py handover <请求文件>`。执行器持有运行锁，核对revision、completed状态、固定流程指纹、所有当前资产和报告哈希，再复制选定CATPart、基准JSON、当前检查报告与确认报告。

handover.json记录参数及范围、运行与代码/流程版本、输入资产指纹、模型发布信息、DS状态和未验收范围。它保留真实fixture_only及确认归属，固定标为development_only，不因流程completed或存在确认记录就变成正式工程发布。确认流程中的测试用确认人也会原样保留，不能当作真实业务签认。

这是读取已完成资产的导出操作，不重新执行旧版本CAD代码，也不要求当前代码与旧运行一致；固定流程和资产必须与其记录一致。运行状态不改写，目标目录不覆盖，复制结果再次按原哈希验证。真实CAS、完整DS、CAE加料及冻结区的验收证明尚未接入此移交接口，因此当前只能输出开发复核包。

## 使用Skill进行开发联调

在启动CATIA前可调用只读`describe`：请求JSON为`{"flow":"tests/fixtures/steering_skeleton_flow.json"}`，运行`python -X utf8 tools/steering_cli.py describe <请求文件>`。输出每步逻辑输入/输出、参数绑定字段的JSON Pointer，以及各参数的直接、下游受影响和不受影响步骤。它复用执行器依赖算法，不创建运行目录、不加载外部CAD清单文件；因此描述成功不表示输入文件可用或工程规则已经验证。

开发模型的get_workflow使用同一说明。模型应先确认候选参数确实影响失败步骤，再依据用户要求和设计关系选值；依赖图只说明影响范围，不说明测量值随参数增减的方向或幅度。描述省略外部清单路径、哈希和固定几何值，不增加修改流程或检查条件的工具。

模型指令位于`skill/steering-wheel-design/SKILL.md`。开发宿主`dev/qwen_steering_acceptance.py`复用已验证的Qwen兼容接口，通过独立CLI进程执行固定流程；最终交付仍是脚本、Skill和配置，不把该开发宿主作为必需Agent。

在仓库根目录、虚拟环境已激活且CATIA已启动时运行：

```powershell
python -X utf8 dev/qwen_steering_acceptance.py "运行方向盘机制夹具。首次厚度8.4毫米，体积检查失败后改为10毫米，继续同一运行，不改变检查条件。" --flow tests/fixtures/steering_baffle_flow.json --allow-cloud --keep-open
```

模型连接使用既有`.env.local`中的QWEN_BASE_URL、QWEN_MODEL和QWEN_API_KEY；不把密钥放入命令或Skill。公网调用需要`--allow-cloud`，正式纯本地部署要求保留。只向模型发送固定流程摘要、可变量和状态/标量测量，不发送CAD文件、输入清单或最近点坐标。

模型工具只开放get_workflow、start_build、inspect_build、resume_build。流程文件由调用方指定并冻结到运行目录；一次会话只允许一次start，模型只能恢复该会话的运行，且只有check_failed可自动改参继续。waiting_confirmation、needs_input和技术异常需要宿主处理，模型没有确认或任意文件访问工具。

`--keep-open`在流程成功后打开最后一个已生成CATPart并聚焦，显示调整不保存到被跟踪资产。调用记录与实际运行保存在runs/qwen-steering-*。模型自然语言报告不作为唯一验收证据，核对transcript中的工具结果和对应state.json。

模型网络中断后，可使用原来的`--flow`并增加`--continue-session runs/qwen-steering-<原会话目录>`续接。宿主恢复原对话和运行ID，检查流程、Skill及运行revision未改变，保留工具调用计数与CAD参数尝试预算；不会重新start。若CAD状态已由其他进程修改，先核对差异，不能用旧会话覆盖它。
