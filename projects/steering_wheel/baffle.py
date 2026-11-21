"""B20原生辐板操作；轮廓与轴系由上游提供，不在此选择工程规则。"""
import math
from . import cad_frame


def _validate_frame(frame,thickness):
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)) or not math.isfinite(thickness) or thickness <= 0:
        raise ValueError('Thickness must be positive finite millimetres')
    if len(frame)!=9:raise ValueError('Expected nine frame coordinates')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in frame):
        raise ValueError('Coordinates must be finite numbers')
    u, v = frame[3:6], frame[6:9]
    if any(abs(sum(a*b for a,b in zip(x,y))-expected)>1e-8
           for x,y,expected in [(u,u,1),(v,v,1),(u,v,0)]):
        raise ValueError('Frame axes must be orthonormal')


def validate_profile(points, frame, thickness):
    _validate_frame(frame,thickness)
    if len(points)<3:raise ValueError('Expected at least three vertices')
    for point in points:
        if len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):
            raise ValueError('Profile vertices must contain two finite coordinates')
    # 首版支持圆周拟合后的凸多边形；拒绝凹、自交、重复及退化轮廓。
    direction = None
    for i, a in enumerate(points):
        b = points[(i+1) % len(points)]
        for j, c in enumerate(points):
            if j in (i, (i+1) % len(points)):
                continue
            cross = (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            if abs(cross)<1e-9:
                raise ValueError('Degenerate polygon')
            sign = cross > 0
            if direction is None:
                direction = sign
            if sign != direction:
                raise ValueError('Expected a simple convex polygon')
    return abs(sum(a[0]*points[(i+1)%len(points)][1]-a[1]*points[(i+1)%len(points)][0]
                   for i,a in enumerate(points)))/2


def create(doc, points, frame, thickness, radius=None):
    """在新Part内创建支撑、闭合草图和单向厚度Pad，返回可编辑特征。"""
    if radius is None:
        validate_profile(points, frame, thickness)
    else:
        if points is not None:raise ValueError('Choose circle radius or polygon outline, not both')
        _validate_frame(frame,thickness)
        if isinstance(radius,bool) or not isinstance(radius,(int,float)) or not math.isfinite(radius) or radius<=0:
            raise ValueError('Radius must be positive finite millimetres')
    part = doc.Part
    supports = part.HybridBodies.Add()
    supports.Name = 'B20_Supports'
    o,u,v = frame[:3],frame[3:6],frame[6:9]
    normal = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    plane = part.HybridShapeFactory.AddNewPlaneEquation(*normal,sum(a*b for a,b in zip(normal,o)))
    supports.AppendHybridShape(plane)
    part.Update()
    body=part.MainBody
    body.Name='B20_Baffle'
    part.InWorkObject=body
    sketch=body.Sketches.Add(part.CreateReferenceFromObject(plane))
    sketch.Name='B20_Outline'
    cad_frame.set_verified(sketch,frame)
    factory=sketch.OpenEdition()
    try:
        if radius is not None:
            circle=factory.CreateClosedCircle(0,0,radius)
            circle.Name='B20_Circle'
        else:
            for index,a in enumerate(points):
                b=points[(index+1)%len(points)]
                factory.CreateLine(*a,*b)
    finally:
        sketch.CloseEdition()
    part.Update()
    pad=part.ShapeFactory.AddNewPad(sketch,thickness)
    pad.Name='B20_Thickness'
    part.Update()
    return pad


def measure(doc):
    pad=doc.Part.MainBody.Shapes.Item('B20_Thickness')
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(pad))
    result={'thickness_mm':pad.FirstLimit.Dimension.Value,
            'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6}
    elements=doc.Part.MainBody.Sketches.Item('B20_Outline').GeometricElements
    for index in range(1,elements.Count+1):
        element=elements.Item(index)
        if element.Name=='B20_Circle':result['radius_mm']=element.Radius
    return result
