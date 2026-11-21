"""沿指定方向与真实曲面求交；只接受搜索区间内唯一顶点。"""
import math
from .datum import unit,vector,dot
from .inputs import resolve_object


def project(app,path,object_path,seed,direction,extent):
    import pythoncom,win32com.client
    if isinstance(extent,bool) or not isinstance(extent,(int,float)) or not math.isfinite(extent) or extent<=0:
        raise ValueError('Projection extent must be positive finite millimetres')
    seed=vector(seed);direction=unit(direction)
    doc=app.Documents.Open(str(path))
    try:
        part=doc.Part;surface=resolve_object(part,object_path)
        factory=part.HybridShapeFactory
        support=part.HybridBodies.Add();support.Name='B10_ProjectionProbe'
        point=factory.AddNewPointCoord(*seed);support.AppendHybridShape(point)
        line=factory.AddNewLinePtDir(part.CreateReferenceFromObject(point),factory.AddNewDirectionByCoord(*direction),-extent,extent,False)
        support.AppendHybridShape(line);part.Update()
        intersection=factory.AddNewIntersection(part.CreateReferenceFromObject(line),part.CreateReferenceFromObject(surface))
        # 扩展模式保留全部候选；下方再核对原面边界与明确的线段区间。
        intersection.IntersectMode=True
        intersection.ExtrapolateMode=False
        support.AppendHybridShape(intersection)
        try:part.Update()
        except Exception as error:raise ValueError('Surface intersection failed; no valid unique projection was obtained') from error
        selection=doc.Selection;selection.Clear();selection.Add(intersection)
        try:
            selection.Search('Topology.CGMVertex,sel')
            references=[selection.Item2(i).Reference for i in range(1,selection.Count2+1)]
        finally:selection.Clear()
        spa=doc.GetWorkbench('SPAWorkbench');surface_measure=spa.GetMeasurable(part.CreateReferenceFromObject(surface))
        candidates=[]
        for reference in references:
            measured=spa.GetMeasurable(reference)
            coordinates=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
            measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPoint'),0,1,0,coordinates)
            candidate=vector(list(coordinates.value));delta=[a-b for a,b in zip(candidate,seed)]
            along=dot(delta,direction)
            if abs(along)>extent+1e-6:continue
            if math.sqrt(sum((v-along*d)**2 for v,d in zip(delta,direction)))>1e-6:continue
            distance=surface_measure.GetMinimumDistance(reference)
            if not math.isfinite(distance):raise ValueError('Invalid point-to-surface distance')
            if distance>1e-6:continue
            if not any(math.dist(candidate,old)<1e-6 for old in candidates):candidates.append(candidate)
        if len(candidates)!=1:raise ValueError('Projection requires one intersection in the declared interval and original surface; found '+str(len(candidates)))
        return {'origin_mm':candidates[0],'extent_mm':extent,'intersection_count':1,'surface_scope':object_path}
    finally:doc.Close()
