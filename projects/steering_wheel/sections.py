"""轮圈截面、扫掠和连接的原生CAD操作；工序顺序由流程负责。"""
import math
from .datum import vector, dot
from . import cad_frame
from .baffle import validate_profile


def rectangle(doc,body,name,frame,width,thickness):
    """中心矩形截面及明确的起始顶点，厚度两侧各占一半。"""
    for value in (width,thickness):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Section dimensions must be positive finite millimetres')
    points=[[-width/2,-thickness/2],[width/2,-thickness/2],
            [width/2,thickness/2],[-width/2,thickness/2]]
    validate_profile(points,frame,thickness)
    part=doc.Part
    origin,x,y=frame[:3],frame[3:6],frame[6:9]
    normal=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    support=part.HybridBodies.Add();support.Name=name+'_Support'
    factory=part.HybridShapeFactory
    plane=factory.AddNewPlaneEquation(*normal,dot(origin,normal))
    support.AppendHybridShape(plane)
    corners=[]
    for index,point in enumerate(points):
        corner=factory.AddNewPointCoord(*[origin[i]+point[0]*x[i]+point[1]*y[i] for i in range(3)])
        corner.Name=name+'_Corner_'+str(index);support.AppendHybridShape(corner);corners.append(corner)
    part.Update();part.InWorkObject=body
    sketch=body.Sketches.Add(part.CreateReferenceFromObject(plane));sketch.Name=name
    cad_frame.set_verified(sketch,frame)
    drawing=sketch.OpenEdition()
    try:
        vertices=[drawing.CreatePoint(*point) for point in points]
        for i,a in enumerate(points):
            edge=drawing.CreateLine(*a,*points[(i+1)%4])
            edge.StartPoint=vertices[i];edge.EndPoint=vertices[(i+1)%4]
    finally:sketch.CloseEdition()
    part.Update()
    return sketch,corners


def circle(doc, body, name, frame, radius):
    if isinstance(radius,bool) or not isinstance(radius,(int,float)) or not math.isfinite(radius) or radius<=0:
        raise ValueError('Radius must be positive finite millimetres')
    if len(frame)!=9:
        raise ValueError('Section frame requires nine coordinates')
    origin=vector(frame[:3]); x=vector(frame[3:6]); y=vector(frame[6:])
    if abs(dot(x,x)-1)>1e-8 or abs(dot(y,y)-1)>1e-8 or abs(dot(x,y))>1e-8:
        raise ValueError('Section frame must be orthonormal')
    part=doc.Part
    normal=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    support=part.HybridBodies.Add();support.Name=name+'_Support'
    plane=part.HybridShapeFactory.AddNewPlaneEquation(*normal,dot(origin,normal))
    support.AppendHybridShape(plane)
    part.Update()
    part.InWorkObject=body
    sketch=body.Sketches.Add(part.CreateReferenceFromObject(plane))
    sketch.Name=name
    cad_frame.set_verified(sketch,frame)
    factory=sketch.OpenEdition()
    try:
        factory.CreateClosedCircle(0,0,radius)
    finally:
        sketch.CloseEdition()
    part.Update()
    return sketch


def sweep(doc, body, profile, guide, name):
    part=doc.Part
    part.InWorkObject=body
    feature=part.ShapeFactory.AddNewRibFromRef(part.CreateReferenceFromObject(profile),part.CreateReferenceFromObject(guide))
    feature.Name=name
    feature.SetKeepAngleOption()
    feature.MoveProfileToPath=False
    part.Update()
    return feature


def bridge(doc, body, profiles, closing_points, name, guides=()):
    """按明确的截面顺序连接；调用者保证端部匹配，保留可编辑Loft。"""
    if len(profiles)<2 or len(profiles)!=len(closing_points):
        raise ValueError('Bridge requires paired sections and closing points')
    part=doc.Part
    part.InWorkObject=body
    feature=part.ShapeFactory.AddNewLoft()
    feature.Name=name
    for profile,point in zip(profiles,closing_points):
        feature.HybridShape.AddSectionToLoft(part.CreateReferenceFromObject(profile),1,part.CreateReferenceFromObject(point))
    for guide in guides:
        feature.HybridShape.AddGuide(part.CreateReferenceFromObject(guide))
    part.Update()
    return feature
