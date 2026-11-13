# -*- coding: utf-8 -*-
"""
按设计意图合并 construct_steps-handleBase 下的 879 个建模步骤，输出 CSV。

合并规则（组内步骤保持连续，可按序重放）：
  A 全局基准   —— 根级直接特征（xy/yz/zx 基准面、绝对轴系）
  B 模型组织   —— MechanicalTool/GSMTool 容器创建，按用途族（功能块体、制造工艺集、
                  构造集、修剪面子集、外部几何、半模型、PMI、配合件、占位集）合并
  C 构造几何   —— body=Part 的 GSM 特征，按 full_path 所属容器链（容器名即设计意图）合并
  D 实体成形   —— 功能几何体内的成形序列（草图→凸台→拔模→倒圆角 等），按几何体合并
  E 布尔整合   —— Add/Remove/Assemble/Trim 布尔运算，按几何体合并
输出：merged_design_intent.csv（UTF-8-BOM，Excel 可直接打开）
"""
import csv
import glob
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
DIR = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(DIR, "merged_design_intent.csv")

# ---------------------------------------------------------------- 基础映射
TYPE_CN = {
    "GSMPlane": "平面", "GSMPoint": "点", "GSMLine": "直线", "GSMMonoDim": "曲线",
    "GSMBiDim": "曲面", "GSMIntersect": "相交", "GSMExtrude": "拉伸",
    "GSMExtrapol": "外插延伸", "GSMSweep": "扫掠", "GSMSplit": "分割", "GSMFill": "填充",
    "GSMOffset": "偏移", "GSMAssemble": "曲面装配", "GSMBoundary": "边界",
    "GSMRotate": "旋转", "GSMMultiExtract": "多重提取", "GSMZeroDim": "零维几何",
    "PRTSketch": "草图", "AxisSystem": "轴系", "MechanicalTool": "几何体容器",
    "GSMTool": "几何集容器", "Pad": "凸台", "Pocket": "凹槽", "Draft": "拔模",
    "EdgeFillet": "倒圆角", "TritangentFillet": "三切线圆角", "Rib": "肋",
    "RectPattern": "矩形阵列", "Thickness": "厚度",
    "Add": "添加", "Remove": "移除", "Assemble": "装配", "Trim": "修剪",
}

# 容器/几何体名称翻译（长词优先）
SEG_CN = [
    ("Rename to TcPLM Part Description", "PLM 重命名占位体"),
    ("Output_Geometry_ForHandleBottomFace", "把手底面输出几何"),
    ("Surport_Geometry_HandleBottmFace", "把手底面支撑几何"),
    ("Geometry_FromHandleASurface", "把手A面来源几何"),
    ("SupportGeo_HandleLimit", "把手限位支撑几何"),
    ("Surport_Geometry_Push", "推块支撑几何"),
    ("Surport_Geometry_Shield", "挡块支撑几何"),
    ("Surport_Geometry_Base", "底座支撑几何"),
    ("Axis_ForStandardParts", "标准件轴线"),
    ("Handle_Screw_Matching_Part", "把手螺钉配合件"),
    ("Handle_With_Face_Rib", "带面筋把手"),
    ("Screw Base Structures", "螺钉座结构"), ("Screw Hole Block", "螺钉孔块"),
    ("Semi-Model Inputs", "半模型输入"), ("Semi-Model Outputs", "半模型输出"),
    ("Main_Tool_Direction", "主脱模方向"), ("Secondary_Tool_Action", "二次抽芯方向"),
    ("Secondary_Action", "二次抽芯"), ("Parting_Lines", "分型线"),
    ("Bumper_Check", "防撞块检查"), ("Screw_head_Check", "螺钉头检查"),
    ("Boss_pillar_Check", "凸台柱检查"), ("Output_Axis", "输出轴线"),
    ("Definition Construction", "定义构造"), ("Construction", "构造"),
    ("Manufacturing", "制造工艺"), ("Styling surface", "造型面"),
    ("Inported geometry", "导入几何"), ("Matching surface", "配合面"),
    ("External geometry", "外部几何"), ("Driving Sketches", "驱动草图"),
    ("Planes", "平面集"), ("Pressure_Spring", "压簧"), ("TRIM SURFACE", "修剪面"),
    ("Basic_Geometry", "基础几何"), ("ICD location", "ICD 定位"),
    ("Actions Support", "抽芯机构支撑"), ("Cavity Support", "型腔支撑"),
    ("Core Support", "型芯支撑"), ("Surport_Geometry", "支撑几何"),
    ("Output_Geometry", "输出几何"), ("3D PMI", "3D PMI 标注"), ("OUTPUTS", "输出"), ("Outputs", "输出"), ("DMU", "DMU 检查"),
    ("Handle_Base", "把手底座"), ("MainBody", "主几何体"), ("Main Base Body", "主体底座"),
    ("Remove Body", "移除体"), ("Two Claws", "双爪体"), ("Left Claw", "左爪体"),
    ("Right Claw", "右爪体"), ("Spring Hole", "弹簧孔体"), ("Bumper Block", "防撞块体"),
    ("Inside Boundary", "内边界体"), ("Deflector Rod Hole", "导杆孔体"),
    ("Top Limint", "顶部限位体"), ("Circle Axis Body", "圆轴体"),
    ("Q block", "Q块"), ("C block", "C块"), ("E block", "E块"), ("I block", "I块"),
    ("J block", "J块"), ("KBE", "KBE"), ("Others", "其他"), ("Base", "基准"),
    ("Main", "主线"),
]
SEG_CN.sort(key=lambda kv: -len(kv[0]))


def tr(text):
    """按关键词词典翻译容器/几何体名，未命中保留原文。"""
    out = text
    for k, v in SEG_CN:
        if k in out:
            out = out.replace(k, v)
    return out


GSM_TYPES = {t for t in TYPE_CN if t.startswith("GSM")} | {"PRTSketch"}
FORM_TYPES = {"Pad", "Pocket", "Draft", "EdgeFillet", "TritangentFillet", "Rib",
              "RectPattern", "Thickness"}
BOOL_TYPES = {"Add", "Remove", "Assemble", "Trim"}
CONTAINER_TYPES = {"MechanicalTool", "GSMTool"}

# ---------------------------------------------------------------- 读取步骤
steps = []
for fp in glob.glob(os.path.join(DIR, "step_*.json")):
    with open(fp, encoding="utf-8") as f:
        d = json.load(f)
    rec = d.get("RECORD", {})
    dfn = d.get("DEFINITION", {})
    steps.append({
        "no": d.get("STEP_NUMBER", 0),
        "type": rec.get("type", ""),
        "body": rec.get("body", ""),
        "name": rec.get("name", ""),
        "fpath": rec.get("full_path", ""),
        "defn": dfn,
        "params": dfn.get("params", {}) or {},
    })
steps.sort(key=lambda s: s["no"])
assert steps and steps[0]["no"] == 1 and steps[-1]["no"] == len(steps), "步骤编号应为 1..N 连续"


def chain_of(s):
    """full_path 去掉根节点与特征名 → 所属容器链；根级返回 ''。"""
    segs = [p for p in s["fpath"].split("/") if p]
    return "/".join(segs[1:-1]) if len(segs) >= 3 else ""


def family_of(s):
    """容器用途族。"""
    segs = [p for p in s["fpath"].split("/") if p][1:]
    if segs[0] == "Manufacturing":
        return "MFG"
    if segs[0].startswith("Semi-Model"):
        return "SEMI"
    if segs[0].startswith("3D PMI"):
        return "PMI"
    if segs[0] == "Construction":
        if len(segs) >= 2 and segs[1] == "Definition Construction":
            if "TRIM SURFACE" in segs:
                return "TRIM"
            if len(segs) >= 3 and segs[2] == "External geometry":
                return "EXT"
        return "CONS"
    if segs[0] in ("Handle_Screw_Matching_Part", "Handle_With_Face_Rib"):
        return "MATCH"
    if s["type"] == "MechanicalTool":
        return "FUNC"          # 功能块几何体 + 编号工作体 + 配合件体
    return "SET"               # 编号占位几何图形集等


def intent_key(s):
    if s["type"] in CONTAINER_TYPES:
        return ("B", family_of(s))
    ch = chain_of(s)
    if s["body"] == "Part":
        return ("A", "") if ch == "" else ("C", ch)
    return ("D", s["body"])    # 实体/布尔特征：按所属几何体


# ---------------------------------------------------------------- 分组
groups, cur = [], None
for s in steps:
    k = intent_key(s)
    if cur and cur["key"] == k:
        cur["steps"].append(s)
    else:
        cur = {"key": k, "steps": [s]}
        groups.append(cur)

# ---------------------------------------------------------------- 描述生成
def comp_str(gs):
    c = Counter(TYPE_CN.get(s["type"], s["type"]) for s in gs)
    return "、".join(f"{t}×{n}" for t, n in c.items())


def names_str(gs, limit=6):
    ns = [s["name"] for s in gs]
    if len(ns) <= limit:
        return "、".join(ns)
    return "、".join(ns[:limit]) + f" 等{len(ns)}个"


def detail_str(gs, limit=4):
    """提取关键参数（拔模角、圆角半径、凸台限位、布尔工具体等）。"""
    ds = []
    for s in gs:
        t, p, dfn = s["type"], s["params"], s["defn"]
        if t == "Draft" and p.get("angle") is not None:
            ds.append(f"拔模{round(p['angle'], 2)}°")
        elif t == "EdgeFillet" and p.get("radius") is not None:
            ds.append(f"R{round(p['radius'], 2)}")
        elif t == "Thickness" and p.get("offset") is not None:
            ds.append(f"厚度{round(p['offset'], 2)}")
        elif t == "Pad":
            l1 = p.get("limit1", {}) or {}
            bits = []
            if l1.get("type"):
                bits.append(l1["type"])
            if l1.get("offset"):
                bits.append(f"偏移{round(l1['offset'], 2)}")
            if bits:
                ds.append("凸台(" + ",".join(bits) + ")")
        elif t == "RectPattern":
            n1, n2 = dfn.get("instances_dir1"), dfn.get("instances_dir2")
            if n1:
                ds.append(f"阵列{n1}×{n2 or 1}")
        elif t in BOOL_TYPES:
            tool = dfn.get("tool_body") or dfn.get("second_operand") or ""
            path = dfn.get("tool_body_path") or dfn.get("second_operand_path") or ""
            name = tool or (path.split("/")[-1] if path else "")
            if name:
                ds.append(f"{TYPE_CN[t]}←{name}")
    uniq = list(dict.fromkeys(ds))
    return "；".join(uniq[:limit])


BFAMILY_DESC = {
    "FUNC": "创建功能块/工作几何体容器",
    "MFG": "创建制造工艺几何集（脱模方向、分型线）",
    "CONS": "创建构造几何集",
    "TRIM": "创建修剪面 TRIM SURFACE 子几何集",
    "EXT": "创建外部输入几何子集（造型面/导入几何/配合面）",
    "SEMI": "创建半模型输入/输出几何集",
    "PMI": "创建 3D PMI 标注输出集",
    "SET": "创建占位几何图形集",
    "MATCH": "创建配合件几何体及其子几何集",
}


def describe(g):
    k = g["key"]
    gs = g["steps"]
    types = {s["type"] for s in gs}
    comp = comp_str(gs)
    det = detail_str(gs)
    det_s = f"（{det}）" if det else ""

    if k[0] == "A":
        if len(gs) == 1 and gs[0]["type"] == "AxisSystem":
            return "创建绝对轴系（全局基准）"
        if types == {"GSMPlane"}:
            return "建立全局基准平面（xy/yz/zx）"
        return f"创建根级直接几何（{comp}）"

    if k[0] == "B":
        return f"{BFAMILY_DESC[k[1]]}（{comp}；{names_str(gs, 5)}）"

    # C / D：定位容器或几何体
    if k[0] == "C":
        loc_raw, loc = k[1], tr(k[1])
    else:
        loc_raw, loc = k[1], tr(k[1])
    where = f"在{loc}（{loc_raw}）中" if loc != loc_raw else f"在{loc}中"

    if types <= GSM_TYPES:
        return f"{where}构建支撑几何（{comp}）"
    if types <= BOOL_TYPES:
        return f"对{loc}进行布尔整合（{comp}）{det_s}"
    if types & BOOL_TYPES and types & (FORM_TYPES | GSM_TYPES):
        return f"{loc}成形与布尔整合（{comp}）{det_s}"
    if types & FORM_TYPES:
        order = {t: i for i, s in enumerate(gs) for t in [s["type"]]}
        seq = [TYPE_CN[t] for t in sorted(types & ({"PRTSketch"} | FORM_TYPES), key=lambda t: order[t])]
        return f"构建{loc}实体（{'→'.join(seq)}）{det_s}"
    return f"{where}构建几何（{comp}）"


def phase_of(g):
    k = g["key"]
    if k[0] == "A":
        return "A-全局基准"
    if k[0] == "B":
        return "B-模型组织"
    types = {s["type"] for s in g["steps"]}
    if k[0] == "C" or types <= GSM_TYPES:
        return "C-构造几何"
    if types <= BOOL_TYPES:
        return "E-布尔整合"
    return "D-实体成形"


def rationale_of(g):
    k = g["key"]
    types = {s["type"] for s in g["steps"]}
    if k[0] == "A":
        return "根级基准特征，独立成组"
    if k[0] == "B":
        return f"连续创建同类容器（{k[1]}）"
    if k[0] == "C":
        return f"同一构造容器 {k[1]} 内的连续几何"
    if types <= BOOL_TYPES:
        return f"几何体 {k[1]} 内的连续布尔运算"
    if types & FORM_TYPES:
        return f"几何体 {k[1]} 内的连续成形特征序列"
    return f"几何体 {k[1]} 内的连续特征"


def range_str(gs):
    a, b = gs[0]["no"], gs[-1]["no"]
    return str(a) if a == b else f"{a}-{b}"


# ---------------------------------------------------------------- 输出 CSV
BFAMILY_CN = {
    "FUNC": "功能块/工作几何体", "MFG": "制造工艺集", "CONS": "构造几何集",
    "TRIM": "修剪面子集", "EXT": "外部输入几何", "SEMI": "半模型集",
    "PMI": "PMI 输出集", "SET": "占位几何图形集", "MATCH": "配合件几何集",
}
rows = []
for i, g in enumerate(groups, 1):
    gs = g["steps"]
    owner = (BFAMILY_CN.get(g["key"][1], g["key"][1]) if g["key"][0] == "B"
             else g["key"][1] if g["key"][0] != "A" else "(根级)")
    rows.append({
        "组号": i,
        "阶段": phase_of(g),
        "设计意图": describe(g),
        "步骤范围": range_str(gs),
        "步骤数": len(gs),
        "所属容器/几何体": owner,
        "特征构成": comp_str(gs),
        "关键特征": names_str(gs),
        "合并依据": rationale_of(g),
    })

with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# ---------------------------------------------------------------- 校验
covered = sum(r["步骤数"] for r in rows)
nums = [s["no"] for g in groups for s in g["steps"]]
assert covered == len(steps) == 879, f"覆盖 {covered} != 879"
assert nums == list(range(1, 880)), "步骤覆盖不连续或有重复"

pc = Counter(r["阶段"] for r in rows)
print(f"已写入 {OUT_CSV}")
print(f"879 个步骤合并为 {len(rows)} 组（压缩比 {879/len(rows):.1f}:1）")
print("各阶段组数:", dict(sorted(pc.items())))
print("各组步骤数分布:", dict(sorted(Counter(r['步骤数'] for r in rows).items())))
print("\n== 预览（前 22 组）==")
for r in rows[:22]:
    print(f'  #{r["组号"]:>3} [{r["阶段"]}] {r["步骤范围"]:>8} x{r["步骤数"]:<3} {r["设计意图"][:80]}')
print("\n== 预览（最后 12 组）==")
for r in rows[-12:]:
    print(f'  #{r["组号"]:>3} [{r["阶段"]}] {r["步骤范围"]:>8} x{r["步骤数"]:<3} {r["设计意图"][:80]}')
print("\n== 最大 8 组 ==")
for r in sorted(rows, key=lambda r: -r["步骤数"])[:8]:
    print(f'  #{r["组号"]:>3} [{r["阶段"]}] {r["步骤范围"]:>8} x{r["步骤数"]:<3} {r["设计意图"][:80]}')
