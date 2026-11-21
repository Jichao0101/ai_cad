"""按显式局部点列和起始截面构建样条轮圈段。"""
import math
from . import sections
from .datum import vector


def create(doc,basis,parameters):
    points=[vector(p) for p in parameters['guide_points_mm']]
    if len(points)<2 or any(sum((a-b)**2 for a,b in zip(p,q))<1e-12 for p,q in zip(points,points[1:])):
        raise ValueError('Spline requires distinct consecutive points')
    def rotate(v):
        return [sum(v[j]*basis[key][i] for j,key in enumerate(['x','y','z'])) for i in range(3)]
    world=[[a+b for a,b in zip(basis['origin_mm'],rotate(p))] for p in points]
    x=rotate(vector(parameters['profile_x']));y=rotate(vector(parameters['profile_y']))
    tangent=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    part=doc.Part;body=part.MainBody;body.Name='B40_SplineSegment'
    profile=sections.circle(doc,body,'B30_Section',world[0]+x+y,parameters['section_radius_mm'])
    support=part.HybridBodies.Add();support.Name='B40_SplineControls'
    factory=part.HybridShapeFactory
    guide=factory.AddNewSpline();guide.SetClosing(0);guide.Name='B40_Spline'
    for index,coordinates in enumerate(world):
        point=factory.AddNewPointCoord(*coordinates);point.Name='GuidePoint_'+str(index)
        support.AppendHybridShape(point)
        reference=part.CreateReferenceFromObject(point)
        if index==0:
            direction=factory.AddNewDirectionByCoord(*tangent)
            guide.AddPointWithConstraintExplicit(reference,direction,1.0,1,None,0.0)
        else:guide.AddPoint(reference)
    support.AppendHybridShape(guide);part.Update()
    result=sections.sweep(doc,body,profile,guide,'B40_Sweep')
    spa=doc.GetWorkbench('SPAWorkbench')
    solid=spa.GetMeasurable(part.CreateReferenceFromObject(result))
    length=spa.GetMeasurable(part.CreateReferenceFromObject(guide)).Length
    return {'volume_mm3':solid.Volume*1e9,'area_mm2':solid.Area*1e6,'guide_length_mm':length,
        'expected_volume_mm3':math.pi*parameters['section_radius_mm']**2*length,
        'section_radius_mm':parameters['section_radius_mm'],'control_points':len(points)}
