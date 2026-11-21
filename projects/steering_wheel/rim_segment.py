"""圆弧引导的轮圈分段操作；CAS自由曲线适配另行接入。"""
import math
from . import sections,cad_frame
from .datum import dot


def create(doc,basis,parameters):
    radius=parameters['guide_radius_mm'];section_radius=parameters['section_radius_mm']
    start=parameters['start_angle_rad'];end=parameters['end_angle_rad']
    if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in [radius,section_radius,start,end]):
        raise ValueError('Arc parameters must be finite numbers')
    if not 0<section_radius<radius or not 0<end-start<2*math.pi:
        raise ValueError('Expected positive tube radius below guide radius and open arc span')
    part=doc.Part;body=part.MainBody;body.Name='B40_RimSegment'
    o,x,y,z=basis['origin_mm'],basis['x'],basis['y'],basis['z']
    radial=[math.cos(start)*a+math.sin(start)*b for a,b in zip(x,y)]
    center=[a+radius*b for a,b in zip(o,radial)]
    profile=sections.circle(doc,body,'B30_Section',center+[-v for v in radial]+z,section_radius)
    supports=part.HybridBodies.Add();supports.Name='B40_GuideSupport'
    plane=part.HybridShapeFactory.AddNewPlaneEquation(*z,dot(o,z))
    supports.AppendHybridShape(plane);part.Update()
    guide=body.Sketches.Add(part.CreateReferenceFromObject(plane));guide.Name='B40_Guide'
    cad_frame.set_verified(guide,o+x+y)
    factory=guide.OpenEdition()
    try:
        curve=factory.CreateCircle(0,0,radius,start,end)
        curve.StartPoint=factory.CreatePoint(radius*math.cos(start),radius*math.sin(start))
        curve.EndPoint=factory.CreatePoint(radius*math.cos(end),radius*math.sin(end))
    finally:guide.CloseEdition()
    part.Update()
    feature=sections.sweep(doc,body,profile,guide,'B40_Sweep')
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(feature))
    return {'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6,
            'section_radius_mm':section_radius,'guide_radius_mm':radius,
            'expected_volume_mm3':math.pi*section_radius**2*radius*(end-start)}
