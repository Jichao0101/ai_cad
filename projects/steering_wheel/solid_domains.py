"""隔离主Body并读取STEP中的显式实体数量；不代替原生连续性或DS检查。"""
import math,re
from pathlib import Path


def read_step(path):
    text=Path(path).read_text(encoding='utf-8',errors='strict')
    # 名称与注释可以包含类似实体定义的文字，先去除它们再识别STEP实体。
    text=re.sub(r"'(?:[^']|'')*'|/\*.*?\*/",'',text,flags=re.S)
    if not text.lstrip().startswith('ISO-10303-21;') or 'END-ISO-10303-21;' not in text:
        raise ValueError('Incomplete STEP exchange file')
    solids=[];shells=0;seen=set()
    for match in re.finditer(r'#(\d+)\s*=\s*(.*?);',text,re.S):
        identifier=int(match[1]);expression=match[2]
        if identifier in seen:raise ValueError('Duplicate STEP entity ID')
        seen.add(identifier)
        types=set(re.findall(r'\b([A-Z][A-Z0-9_]*)\s*\(',expression))
        if types & {'MAPPED_ITEM','CSG_SOLID','BOOLEAN_RESULT','SHELL_BASED_SURFACE_MODEL','OPEN_SHELL'}:
            raise ValueError('STEP contains unsupported mapped, implicit or open-surface topology')
        if types & {'MANIFOLD_SOLID_BREP','BREP_WITH_VOIDS','FACETED_BREP'}:solids.append(identifier)
        if 'CLOSED_SHELL' in types:shells+=1
    if not solids or not shells:raise ValueError('STEP has no explicit closed solid representation')
    return {'step_solid_count':len(solids),'step_closed_shell_count':shells}


def measure(app,source,path):
    """在临时Part中仅复制最终主实体，导出留证；不保存或更改输入Part。"""
    path=Path(path)
    if path.exists():raise ValueError('STEP evidence path already exists')
    source_doc=app.Documents.Open(str(source));target=None
    try:
        original=source_doc.GetWorkbench('SPAWorkbench').GetMeasurable(source_doc.Part.CreateReferenceFromObject(source_doc.Part.MainBody)).Volume*1e9
        selection=source_doc.Selection;selection.Clear();selection.Add(source_doc.Part.MainBody)
        try:selection.Copy()
        finally:selection.Clear()
        target=app.Documents.Add('Part');selection=target.Selection
        selection.Clear();selection.Add(target.Part)
        try:selection.PasteSpecial('CATPrtResultWithOutLink')
        finally:selection.Clear()
        part=target.Part;part.Update()
        nonempty=[part.Bodies.Item(i) for i in range(1,part.Bodies.Count+1) if part.Bodies.Item(i).Shapes.Count]
        if len(nonempty)!=1:raise ValueError('Expected one isolated copied Body')
        part.MainBody=nonempty[0]
        copied=target.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
        if not math.isfinite(original) or original<=0 or not math.isfinite(copied) or abs(original-copied)>max(1e-6,original*1e-9):
            raise ValueError('Isolated main body volume differs from source')
        target.ExportData(str(path),'stp')
        return {**read_step(path),'source_volume_mm3':original,'copied_volume_mm3':copied,
                'measurement_method':'isolated_main_body_step_export'}
    finally:
        if target is not None:target.Close()
        source_doc.Close()
