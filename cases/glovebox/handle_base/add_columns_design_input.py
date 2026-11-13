# -*- coding: utf-8 -*-
"""
为 merged_design_intent.csv 增加『设计输入』『可变参数』两列（插在“设计意图”之后）。

数据来源：
  - 各行“步骤范围”对应的 step_*.json（RECORD.type / DEFINITION.params /
    positioning / tool_body），优先精确提取；
  - JSON 缺失或字段不全时回退到“设计意图”文本与类型通用表述。
输出：原文件重写为 11 列（UTF-8-BOM，Excel 可直接打开）。
"""
import csv
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(DIR, "merged_design_intent.csv")

TYPE_CN = {
    "Pad": "凸台", "Draft": "拔模", "EdgeFillet": "倒圆角",
    "TritangentFillet": "三切线内圆角", "Rib": "肋", "RectPattern": "矩形阵列",
    "Thickness": "厚度", "PRTSketch": "草图",
    "Add": "添加", "Remove": "移除", "Assemble": "装配", "Trim": "修剪",
}
BOOL_TYPES = {"Add", "Remove", "Assemble", "Trim"}

# ---------------------------------------------------------------- 工具函数
def fmt(x):
    v = round(float(x), 2)
    return str(int(v)) if v == int(v) else str(v)


def joinuniq(parts, cap=8):
    """去重保序，超限截断加“等”。"""
    uniq = list(dict.fromkeys(parts))
    if len(uniq) > cap:
        return "；".join(uniq[:cap]) + " 等"
    return "；".join(uniq)


def parse_range(s):
    s = s.strip()
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(s)]


def text_params(txt):
    """从设计意图文本兜底提取参数片段。"""
    ms = re.findall(r"(偏移[-\d.]+|拔模-?[\d.]+°|R[\d.]+|阵列\d+×\d+|厚度[\d.]+)", txt)
    return "；".join(dict.fromkeys(ms))


# ---------------------------------------------------------------- step 索引
step_files = {}
for fp in glob.glob(os.path.join(DIR, "step_*.json")):
    m = re.match(r"step_(\d+)_", os.path.basename(fp))
    if m:
        step_files[int(m.group(1))] = fp

_cache = {}


def fillet_source(dfn):
    """倒圆角所选边的原始特征名。"""
    for sel in dfn.get("selections") or []:
        for brep in sel.get("resolved_breps") or []:
            init = brep.get("initial_feature") or {}
            if init.get("name"):
                return init["name"]
    return None


def load(n):
    if n in _cache:
        return _cache[n]
    s = None
    fp = step_files.get(n)
    if fp:
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            rec = d.get("RECORD") or {}
            dfn = d.get("DEFINITION") or {}
            p = dfn.get("params")
            s = {
                "type": rec.get("type", ""),
                "name": rec.get("name", ""),
                "defn": dfn,
                "params": p if isinstance(p, dict) else {},
                "fillet_src": fillet_source(dfn),
            }
        except Exception:
            s = None
    _cache[n] = s
    return s


def sketch_pos(dfn):
    pos = dfn.get("positioning") or {}
    sup = [r.get("name") for r in pos.get("support_references") or [] if isinstance(r, dict)]
    org = [r.get("name") for r in pos.get("origin_references") or [] if isinstance(r, dict)]
    return [x for x in sup if x], [x for x in org if x]


# ---------------------------------------------------------------- A/B 阶段
def gen_A(row):
    if "轴系" in row["特征构成"]:
        return ("CATIA 缺省参考系（绝对坐标系原点与三轴向）",
                "无（轴系随绝对坐标系固定）")
    return ("CATIA 缺省参考系（xy/yz/zx 三基准平面、绝对坐标系）",
            "无（全局基准固定，为全模型定位原点）")


BFAM_IN = {
    "FUNC": "产品设计方案（功能块/工作体划分：主体、爪体、Q块、螺钉座、防撞块等）",
    "MATCH": "配合件设计需求（螺钉配合件、带面筋把手等配合结构定义）",
    "MFG": "模具工艺方案（主/二次抽芯方向、分型线定义）",
    "CONS": "构造策略（各功能块的支撑几何分类组织方案）",
    "TRIM": "修剪面分区方案（A面来源/限位/推块/挡块/底座/把手底面等分区）",
    "EXT": "外部几何输入清单（造型A面、导入几何、配合面）",
    "SEMI": "半模型交换需求（输入/输出几何与 DMU 检查项）",
    "PMI": "3D 标注输出需求（PMI 输出分组）",
    "SET": "模型占位/结构组织需求",
}
B_VAR = "容器命名、数量与层级结构（纯组织，无几何参数）"


def gen_B(row):
    m = re.search(r"（([A-Z]+)）\s*$", row["合并依据"])
    fam = m.group(1) if m else "SET"
    return BFAM_IN.get(fam, BFAM_IN["SET"]), B_VAR


# ---------------------------------------------------------------- C 阶段
C_TYPE_IN = {
    "平面": "参考平面/基准面与定位方向（偏移或角度定位）",
    "点": "参考几何（基准面、曲线、曲面上的定位参考）",
    "直线": "参考点与方向（点-方向/两点式）",
    "曲线": "参考几何（点、平面、曲面边界或交线）",
    "曲面": "源几何（外部A面、边界曲线或源曲面）",
    "相交": "两组被求交几何（平面/曲面/曲线）",
    "拉伸": "轮廓曲线 + 拉伸方向",
    "外插延伸": "边界边/曲线 + 相切延续参考",
    "扫掠": "轮廓曲线 + 引导曲线",
    "分割": "被分割几何 + 分割元素",
    "填充": "闭合边界曲线",
    "偏移": "源曲面/曲线 + 偏移方向",
    "曲面装配": "多张待装配的源曲面",
    "边界": "源曲面边界",
    "旋转": "轮廓 + 旋转轴",
    "多重提取": "源几何子元素（边/面）",
    "零维几何": "参考几何（端点/交点）",
    "轴系": "参考点/平面与方向",
    "草图": "定位支持面 + 原点参考",
}
C_TYPE_VAR = {
    "平面": "平面的偏移距离、角度与参考方向",
    "点": "点位置/坐标",
    "直线": "起止点与长度",
    "曲线": "曲线形状参数",
    "曲面": "曲面形状参数",
    "相交": "无独立参数（由被交几何决定）",
    "拉伸": "拉伸长度与方向",
    "外插延伸": "延伸长度（常量/直到条件）",
    "扫掠": "扫掠截面位置与角度修正",
    "分割": "保留侧选择",
    "填充": "无独立参数（由边界决定）",
    "偏移": "偏移距离",
    "曲面装配": "无独立参数（由源曲面决定）",
    "边界": "无独立参数（由源曲面决定）",
    "旋转": "旋转角度与轴",
    "多重提取": "提取元素选择",
    "零维几何": "无独立参数",
    "轴系": "轴系原点与方向",
    "草图": "草图内轮廓尺寸与几何约束",
}


def gen_C(row, nums):
    comps = re.findall(r"([^\s、×]+)×(\d+)", row["特征构成"])
    # 收集组内草图的定位信息
    sketches = []
    for n in nums:
        s = load(n)
        if s and s["type"] == "PRTSketch":
            sup, org = sketch_pos(s["defn"])
            sketches.append((s["name"], sup, org))
    ins_parts, var_parts = [], []
    for t, c in comps:
        if t == "草图" and sketches:
            sup = list(dict.fromkeys([x for sk in sketches for x in sk[1]]))
            org = list(dict.fromkeys([x for sk in sketches for x in sk[2]]))
            seg = f"草图×{c}：支持面（{'、'.join(sup[:4])}"
            if org:
                seg += f"）+ 原点参考（{'、'.join(org[:2])}"
            ins_parts.append(seg + "）")
        else:
            ins_parts.append(f"{t}×{c}：{C_TYPE_IN.get(t, '上游参考几何')}")
        var_parts.append(f"{t}×{c}：{C_TYPE_VAR.get(t, '几何定义参数')}")
    return joinuniq(ins_parts, cap=6), joinuniq(var_parts, cap=6)


# ---------------------------------------------------------------- D 阶段
def d_desc(s):
    """单个成形步骤 →（设计输入片段, 可变参数片段）。"""
    t, p, dfn = s["type"], s["params"], s["defn"]

    if t == "Pad":
        prof = [e["name"] for e in (p.get("profile_elements") or [])
                if isinstance(e, dict) and e.get("name")]
        lim_refs, lim_offs = [], []
        for key in ("limit1", "limit2"):
            lim = p.get(key) or {}
            if not isinstance(lim, dict):
                continue
            if lim.get("up_to"):
                lim_refs.append(lim["up_to"] if lim["up_to"] != "Support" else "草图支持面")
            if lim.get("offset") is not None:
                lim_offs.append(fmt(lim["offset"]))
        ins = "凸台：轮廓草图（" + "、".join(prof) + "）" if prof else "凸台：轮廓草图"
        if lim_refs:
            ins += "，限位参考（" + "、".join(lim_refs) + "）"
        offs = [x for x in lim_offs if x != "0"]  # 第二限位偏移常为 0（直达支持面），不展示
        var = "凸台限位偏移（" + "/".join(offs) + "）" if offs else "凸台限位偏移量"
        return ins, var

    if t == "Draft":
        neutral = p.get("neutral") or "中性面"
        pull = p.get("pulling_direction_ref") or "拔模方向参考"
        ins = f"拔模：中性面（{neutral}）+ 拔模方向（{pull}）"
        ang = p.get("angle")
        var = f"拔模角度（{fmt(ang)}°）" if ang is not None else "拔模角度"
        return ins, var

    if t == "EdgeFillet":
        src = s.get("fillet_src")
        ins = f"倒圆角：所选棱边（源自{src}）" if src else "倒圆角：所选棱边（成形特征边界）"
        r = p.get("radius")
        var = f"圆角半径（R{fmt(r)}）" if r is not None else "圆角半径"
        return ins, var

    if t == "TritangentFillet":
        return "三切线内圆角：三个相切参考面", "无独立半径（由三切面位置决定）"

    if t == "Rib":
        prof = [e["name"] for e in (p.get("profile_elements") or [])
                if isinstance(e, dict) and e.get("name")]
        center = (p.get("center_curve") or {}).get("name")
        ins = "肋：轮廓草图（" + "、".join(prof) + "）"
        if center:
            ins += f" + 中心曲线（{center}）"
        return ins, "肋轮廓尺寸与中心曲线形状"

    if t == "Thickness":
        off = p.get("offset")
        var = f"加厚偏移量（{fmt(off)}）" if off is not None else "加厚偏移量"
        return "厚度：所选要加厚的实体面", var

    if t == "RectPattern":
        n1 = dfn.get("instances_dir1") or 1
        n2 = dfn.get("instances_dir2") or 1
        d1 = dfn.get("direction1")
        src = dfn.get("source_feature")
        ins = "阵列：被阵列特征（" + (src or "前序成形特征") + "）"
        if d1:
            ins += f"，方向参考（{d1}）"
        st = dfn.get("step_dir1")
        var = f"实例数（{n1}×{n2}）"
        if st:
            var += f"与间距（{fmt(abs(st))}）"
        return ins, var

    if t == "PRTSketch":
        return "草图：定位支持面 + 原点参考（实体轮廓）", "草图内轮廓尺寸与几何约束"

    if t in BOOL_TYPES:
        tool = dfn.get("tool_body") or dfn.get("second_operand") or ""
        ins = f"{TYPE_CN.get(t, t)}：工具体（{tool}）" if tool else f"{TYPE_CN.get(t, t)}：工具体"
        return ins, "布尔类型与工具体选择（无尺寸参数）"

    return None


def gen_D(row, nums):
    ins_parts, var_parts = [], []
    for n in nums:
        s = load(n)
        if not s:
            continue
        r = d_desc(s)
        if r:
            ins_parts.append(r[0])
            var_parts.append(r[1])
    if not ins_parts:
        tp = text_params(row["设计意图"])
        return ("上游草图轮廓与参考几何（凸台/拔模/圆角等成形输入）",
                tp or "成形尺寸参数（限位偏移/拔模角/圆角半径）")
    return joinuniq(ins_parts, cap=8), joinuniq(var_parts, cap=8)


# ---------------------------------------------------------------- E 阶段
def gen_E(row, nums):
    tools = []
    for n in nums:
        s = load(n)
        if s:
            tool = (s["defn"].get("tool_body") or s["defn"].get("second_operand") or "")
            if tool:
                tools.append(f"{TYPE_CN.get(s['type'], s['type'])}←{tool}")
    if not tools:
        tools = [t.strip() for t in
                 re.findall(r"(?:添加|移除|装配|修剪)←([^；)）]+)", row["设计意图"])]
    ins = f"目标体（{row['所属容器/几何体']}）+ 工具体（" + \
          "、".join(tools[:6]) + ("等" if len(tools) > 6 else "") + "）"
    var = "布尔运算类型（添加/移除/装配/修剪）与工具体选择（无尺寸参数）"
    return ins, var


# ---------------------------------------------------------------- 主流程
with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    fields_in = list(reader.fieldnames or [])

# 支持重复运行：若已有新列则剥离后重新生成
fields_in = [k for k in fields_in if k not in ("设计输入", "可变参数")]

new_rows = []
for row in rows:
    nums = parse_range(row["步骤范围"])
    ph = row["阶段"]
    if ph.startswith("A"):
        a, b = gen_A(row)
    elif ph.startswith("B"):
        a, b = gen_B(row)
    elif ph.startswith("C"):
        a, b = gen_C(row, nums)
    elif ph.startswith("D"):
        a, b = gen_D(row, nums)
    else:
        a, b = gen_E(row, nums)
    new = {}
    for k in fields_in:
        new[k] = row[k]
        if k == "设计意图":
            new["设计输入"] = a
            new["可变参数"] = b
    new_rows.append(new)

fields_out = []
for k in fields_in:
    fields_out.append(k)
    if k == "设计意图":
        fields_out += ["设计输入", "可变参数"]

with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields_out, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    w.writerows(new_rows)

# ---------------------------------------------------------------- 校验与预览
assert len(new_rows) == len(rows)
for r in new_rows:
    assert None not in r and "" not in (r["设计输入"], r["可变参数"]), f"组{r['组号']} 新列为空"

from collections import Counter
pc = Counter(r["阶段"] for r in new_rows)
print(f"已写入 {CSV_PATH}")
print(f"行数 {len(new_rows)}，列数 {len(fields_out)}：{','.join(fields_out)}")
print("各阶段组数:", dict(sorted(pc.items())))
print("JSON 覆盖: %d / 879 步已建立索引" % len(step_files))

samples = [1, 9, 22, 41, 42, 63, 82, 102, 115, 153, 187, 188]
print("\n== 抽样预览 ==")
for r in new_rows:
    if int(r["组号"]) in samples:
        print(f"\n#{r['组号']} [{r['阶段']}] {r['步骤范围']} {r['设计意图'][:60]}")
        print(f"  设计输入: {r['设计输入']}")
        print(f"  可变参数: {r['可变参数']}")
