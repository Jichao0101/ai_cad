"""B20圆形底罩截线：真实面求交、闭圆核验及明确径向内缩。"""
import math
from .datum import dot,vector
from .inputs import resolve_object


def extract(app,path,object_path,basis,inset,plane_offset=0):
    import pythoncom,win32com.client
    if isinstance(inset,bool) or not isinstance(inset,(int,float)) or not math.isfinite(inset) or inset<0:
        raise ValueError('Radial inset must be nonnegative finite millimetres')
    if isinstance(plane_offset,bool) or not isinstance(plane_offset,(int,float)) or not math.isfinite(plane_offset):
        raise ValueError('Section plane offset must be finite millimetres')
    plane_origin=[a+plane_offset*b for a,b in zip(basis['origin_mm'],basis['z'])]
    doc=app.Documents.Open(str(path))
    try:
        part=doc.Part;surface=resolve_object(part,object_path)
        factory=part.HybridShapeFactory
        support=part.HybridBodies.Add();support.Name='B20_SectionProbe'
        plane=factory.AddNewPlaneEquation(*basis['z'],dot(plane_origin,basis['z']))
        support.AppendHybridShape(plane);part.Update()
        curve=factory.AddNewIntersection(part.CreateReferenceFromObject(plane),part.CreateReferenceFromObject(surface))
        curve.ExtendMode=0;curve.ExtrapolateMode=False
        support.AppendHybridShape(curve);part.Update()
        measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(curve))
        radius=float(measured.Radius);length=float(measured.Length)
        if not math.isfinite(radius) or radius<=0 or not math.isfinite(length) or abs(length-2*math.pi*radius)>1e-6:
            raise ValueError('Expected exactly one complete circular section; noncircular fitting is not implemented')
        if inset>=radius:raise ValueError('Radial inset consumes the entire circular profile')
        coordinates=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetCenter'),0,1,0,coordinates)
        center=vector(list(coordinates.value))
        if abs(dot([a-b for a,b in zip(center,plane_origin)],basis['z']))>1e-6:
            raise ValueError('Measured circle center is outside the section plane')
        return {'radius_mm':radius-inset,'source_radius_mm':radius,'source_length_mm':length,
                'radial_inset_mm':inset,'plane_offset_mm':plane_offset,'center_mm':center,'sketch_frame':center+basis['x']+basis['y'],'surface_scope':object_path}
    finally:doc.Close()
