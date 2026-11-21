"""B10：用显式配对的四个CAS点构建并核对共同垂直平分面。"""
import math
from .datum import vector,unit,dot
from .inputs import resolve_object


def solve(pairs,positive_normal):
    """第一对确定候选面，第二对验证；不做最佳拟合或自动重新配对。"""
    if len(pairs)!=2 or any(len(pair)!=2 for pair in pairs):
        raise ValueError('Symmetry requires exactly two point pairs')
    pairs=[[vector(point) for point in pair] for pair in pairs]
    midpoints=[[(a+b)/2 for a,b in zip(*pair)] for pair in pairs]
    if math.dist(*midpoints)<1e-6:raise ValueError('Symmetry pair midpoints must be distinct')
    for pair in pairs:
        if math.dist(*pair)<1e-6:raise ValueError('Symmetry pair must contain distinct points')
    normal=unit([b-a for a,b in zip(*pairs[0])])
    orientation=dot(normal,unit(positive_normal))
    if abs(orientation)<1e-8:raise ValueError('Positive normal does not determine symmetry orientation')
    if orientation<0:normal=[-v for v in normal]
    point=midpoints[0]
    deviations=[]
    for left,right in pairs:
        distance=dot([a-b for a,b in zip(left,point)],normal)
        mirrored=[a-2*distance*n for a,n in zip(left,normal)]
        deviations.append(math.dist(mirrored,right))
    # 此处是共同平面构造一致性，而非整张CAS的工程对称公差。
    if max(deviations)>1e-6:
        raise ValueError('Point pairs do not define one common symmetry plane; mirror deviations mm: '+str(deviations))
    return {'point_mm':point,'normal':normal,'pairs_mm':pairs,'midpoints_mm':midpoints,
            'pair_mirror_deviations_mm':deviations,'maximum_pair_deviation_mm':max(deviations)}


def extract(app,path,object_pairs,positive_normal):
    """从运行副本读四个具名点；不修改或保存输入Part。"""
    import pythoncom,win32com.client
    if len(object_pairs)!=2 or any(len(pair)!=2 for pair in object_pairs):
        raise ValueError('Symmetry requires exactly two bound point pairs')
    doc=app.Documents.Open(str(path))
    try:
        part=doc.Part;spa=doc.GetWorkbench('SPAWorkbench');pairs=[]
        for object_pair in object_pairs:
            pair=[]
            for object_path in object_pair:
                obj=resolve_object(part,object_path)
                measured=spa.GetMeasurable(part.CreateReferenceFromObject(obj))
                coordinates=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
                measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPoint'),0,1,0,coordinates)
                pair.append(vector(list(coordinates.value)))
            pairs.append(pair)
        return {**solve(pairs,positive_normal),'point_scopes':object_pairs}
    finally:doc.Close()
