"""B40按明确基准平面与输入曲面求交，保留原生引导线依赖。"""
import math
from .datum import dot,vector
from .inputs import resolve_object


def create(doc,surface_path,basis,offset,start_hint=None):
    import pythoncom,win32com.client
    if isinstance(offset,bool) or not isinstance(offset,(int,float)) or not math.isfinite(offset):
        raise ValueError('Guide plane offset must be finite millimetres')
    if start_hint is not None:start_hint=vector(start_hint)
    normal=vector(basis['z']);origin=vector(basis['origin_mm'])
    if abs(dot(normal,normal)-1)>1e-8:raise ValueError('Guide plane normal must be a unit direction')
    part=doc.Part;surface=resolve_object(part,surface_path);name='B40_SurfaceGuide'
    if any(part.HybridBodies.Item(i).Name==name for i in range(1,part.HybridBodies.Count+1)):
        raise ValueError('Surface guide support already exists')
    support=part.HybridBodies.Add();support.Name=name;factory=part.HybridShapeFactory
    plane_origin=[a+offset*b for a,b in zip(origin,normal)]
    plane=factory.AddNewPlaneEquation(*normal,dot(plane_origin,normal));plane.Name='GuidePlane'
    support.AppendHybridShape(plane);part.UpdateObject(plane)
    curve=factory.AddNewIntersection(part.CreateReferenceFromObject(plane),part.CreateReferenceFromObject(surface))
    curve.Name='GuideIntersection';curve.ExtendMode=0;curve.ExtrapolateMode=False
    support.AppendHybridShape(curve);part.UpdateObject(curve)
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(curve))
    length=measured.Length
    if not math.isfinite(length) or length<=1e-6:raise ValueError('Surface intersection has no measurable guide length')
    values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
    measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPointsOnCurve'),0,1,0,values)
    points=[vector(list(values.value)[i:i+3]) for i in (0,3,6)]
    if math.dist(points[0],points[2])<1e-6:raise ValueError('Closed intersection requires an explicit segmentation rule')
    if any(abs(dot([a-b for a,b in zip(point,plane_origin)],normal))>1e-6 for point in points):
        raise ValueError('Intersection measurements do not lie on the declared plane')
    reversed_guide=False
    if start_hint is not None:
        distances=[math.dist(start_hint,point) for point in (points[0],points[2])]
        if abs(distances[0]-distances[1])<=1e-6:
            raise ValueError('Start hint is equidistant from the guide ends; orientation is ambiguous')
        reversed_guide=distances[1]<distances[0]
        expected_start,expected_end=(points[2],points[0]) if reversed_guide else (points[0],points[2])
        curve.Name='GuideIntersectionRaw'
        curve=factory.AddNewInverse(part.CreateReferenceFromObject(curve),-1 if reversed_guide else 1)
        curve.Name='GuideIntersection';support.AppendHybridShape(curve);part.UpdateObject(curve)
        measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(curve))
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPointsOnCurve'),0,1,0,values)
        points=[vector(list(values.value)[i:i+3]) for i in (0,3,6)]
        if abs(measured.Length-length)>1e-6 or math.dist(points[0],expected_start)>1e-6 or math.dist(points[2],expected_end)>1e-6:
            raise ValueError('Native curve orientation differs from the selected start end')
    return {'guide_length_mm':length,'plane_offset_mm':offset,'guide_points_mm':points,
            'direction_from_hint':start_hint is not None,'guide_reversed':reversed_guide,
            'guide_path':[{'collection':'HybridBodies','name':name},{'collection':'HybridShapes','name':curve.Name}],
            'surface_scope':surface_path}
