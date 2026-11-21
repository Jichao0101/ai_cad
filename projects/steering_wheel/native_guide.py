"""从工作副本中的具名原生曲线建立法向截面和Rib。"""
import math
from . import sections
from .inputs import resolve_object
from .datum import unit,dot


def _circle_end_sections(doc,reference,support,radius):
    """读回引导线两端的法向截面；圆截面不依赖扫掠中的绕轴转角。"""
    import pythoncom,win32com.client
    part=doc.Part;factory=part.HybridShapeFactory;spa=doc.GetWorkbench('SPAWorkbench');result={}
    # 过近的样条百分比点可能被内核吸附到端点；短弦只定正负，不作为法向或DS容差。
    for label,fraction,near_fraction in [('start',0.0,.001),('end',1.0,.999)]:
        coordinates=[];points=[]
        for index,value in enumerate([fraction,near_fraction]):
            point=factory.AddNewPointOnCurveFromPercent(reference,value,False)
            point.Name='B45_'+label+'_Point_'+str(index);support.AppendHybridShape(point);part.UpdateObject(point)
            measured=spa.GetMeasurable(part.CreateReferenceFromObject(point))
            values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
            measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPoint'),0,1,0,values)
            coordinates.append(list(values.value));points.append(point)
        plane=factory.AddNewPlaneNormal(reference,part.CreateReferenceFromObject(points[0]))
        plane.Name='B45_'+label+'_Plane';support.AppendHybridShape(plane);part.UpdateObject(plane)
        measured=spa.GetMeasurable(part.CreateReferenceFromObject(plane))
        values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPlane'),0,1,0,values)
        x,y=list(values.value[3:6]),list(values.value[6:9])
        normal=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
        travel=unit([b-a for a,b in zip(coordinates[0],coordinates[1])])
        if label=='end':travel=[-v for v in travel]
        alignment=dot(normal,travel)
        if abs(alignment)<1e-8:raise ValueError('Endpoint plane cannot determine guide orientation')
        if alignment<0:x=[-v for v in x]
        result[label]={'center_mm':coordinates[0],'x':x,'y':y,'radius_mm':radius}
    _verify_circle_end_faces(doc,result)
    return {'coordinate_system':'design_global','section_kind':'circle','sections':result}


def _verify_circle_end_faces(doc,end_sections):
    """将引导线推导的圆截面与实际Rib端面核对；容差仅用于几何身份一致性。"""
    import pythoncom,win32com.client
    selection=doc.Selection;selection.Clear();selection.Add(doc.Part.MainBody)
    try:
        selection.Search('Topology.CGMFace,sel')
        references=[selection.Item2(i).Reference for i in range(1,selection.Count2+1)]
    finally:selection.Clear()
    spa=doc.GetWorkbench('SPAWorkbench');faces=[]
    for reference in references:
        measured=spa.GetMeasurable(reference)
        # 本机SPA实际平面端面的GeometryName为7；不将侧面近似成端面。
        if measured.GeometryName!=7:continue
        center=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
        plane=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
        for method,value in [('GetCOG',center),('GetPlane',plane)]:
            measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames(method),0,1,0,value)
        x,y=list(plane.value[3:6]),list(plane.value[6:9])
        normal=unit([x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]])
        faces.append((list(center.value),normal,measured.Area*1e6))
    matched=[]
    for label,spec in end_sections.items():
        x,y=spec['x'],spec['y']
        normal=unit([x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]])
        expected_area=math.pi*spec['radius_mm']**2
        candidates=[i for i,(center,axis,area) in enumerate(faces)
                    if math.dist(center,spec['center_mm'])<=1e-6
                    and abs(abs(dot(normal,axis))-1)<=1e-8 and abs(area-expected_area)<=1e-6]
        if len(candidates)!=1 or candidates[0] in matched:
            raise ValueError('Sweep endpoint does not match one distinct planar circular cap: '+label)
        matched.append(candidates[0])


def create(doc,object_path,radius=None,start_fraction=0,end_fraction=1,rectangle=None):
    import pythoncom,win32com.client
    if (radius is None)==(rectangle is None):raise ValueError('Choose circular radius or rectangle section exclusively')
    if rectangle is None:
        if isinstance(radius,bool) or not isinstance(radius,(int,float)) or not math.isfinite(radius) or radius<=0:
            raise ValueError('Section radius must be positive finite millimetres')
    else:
        width=rectangle['width_mm'];thickness=rectangle['thickness_mm']
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in [width,thickness]):
            raise ValueError('Rectangle dimensions must be positive finite millimetres')
        up=unit(rectangle['thickness_direction'])
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [start_fraction,end_fraction]) or not 0<=start_fraction<end_fraction<=1:
        raise ValueError('Guide interval must satisfy 0 <= start_fraction < end_fraction <= 1')
    part=doc.Part;guide=resolve_object(part,object_path)
    reference=part.CreateReferenceFromObject(guide);original_reference=reference
    spa=doc.GetWorkbench('SPAWorkbench')
    curve_measure=spa.GetMeasurable(reference)
    length=curve_measure.Length
    if not math.isfinite(length) or length<=1e-6:raise ValueError('Guide must have positive length')
    samples=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
    curve_measure._oleobj_.Invoke(curve_measure._oleobj_.GetIDsOfNames('GetPointsOnCurve'),0,1,0,samples)
    if math.dist(samples.value[:3],samples.value[6:9])<1e-6:
        raise ValueError('Guide must be an explicitly selected open segment')
    support=part.HybridBodies.Add();support.Name='B30_NativeGuideSupport'
    factory=part.HybridShapeFactory
    source_length=length
    expected_ends=[]
    # 两个裁剪点均取自原曲线，避免第二个比例被解释为剩余段的比例。
    for label,fraction,side in [('Start',start_fraction,-1),('End',end_fraction,1)]:
        point=factory.AddNewPointOnCurveFromPercent(original_reference,float(fraction),False)
        point.Name='B40_Trim'+label;support.AppendHybridShape(point);part.UpdateObject(point)
        point_measure=spa.GetMeasurable(part.CreateReferenceFromObject(point))
        coordinates=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
        point_measure._oleobj_.Invoke(point_measure._oleobj_.GetIDsOfNames('GetPoint'),0,1,0,coordinates)
        expected_ends.append(list(coordinates.value))
        if (label=='Start' and fraction>0) or (label=='End' and fraction<1):
            guide=factory.AddNewHybridSplit(reference,part.CreateReferenceFromObject(point),side)
            guide.Name='B40_TrimAfter'+label;support.AppendHybridShape(guide);part.UpdateObject(guide)
            reference=part.CreateReferenceFromObject(guide)
    curve_measure=spa.GetMeasurable(reference);length=curve_measure.Length
    curve_measure._oleobj_.Invoke(curve_measure._oleobj_.GetIDsOfNames('GetPointsOnCurve'),0,1,0,samples)
    if math.dist(samples.value[:3],expected_ends[0])>1e-6 or math.dist(samples.value[6:9],expected_ends[1])>1e-6:
        raise ValueError('Trimmed guide endpoints do not match the declared interval')
    start=factory.AddNewPointOnCurveFromPercent(reference,0.0,False)
    start.Name='B30_GuideStart';support.AppendHybridShape(start)
    plane=factory.AddNewPlaneNormal(reference,part.CreateReferenceFromObject(start))
    plane.Name='B30_GuideNormal';support.AppendHybridShape(plane);part.Update()
    measured=spa.GetMeasurable(part.CreateReferenceFromObject(plane))
    frame=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
    measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPlane'),0,1,0,frame)
    # 测量平面的原点未必是曲线起点，显式读回起点替换截面中心。
    point=spa.GetMeasurable(part.CreateReferenceFromObject(start))
    coordinates=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
    point._oleobj_.Invoke(point._oleobj_.GetIDsOfNames('GetPoint'),0,1,0,coordinates)
    section_frame=list(coordinates.value)+list(frame.value[3:])
    if rectangle is not None:
        x,y=section_frame[3:6],section_frame[6:9]
        normal=unit([x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]])
        projection=[v-dot(up,normal)*n for v,n in zip(up,normal)]
        if math.sqrt(dot(projection,projection))<1e-8:
            raise ValueError('Thickness direction is parallel to the guide tangent')
        y=unit(projection)
        x=[y[1]*normal[2]-y[2]*normal[1],y[2]*normal[0]-y[0]*normal[2],y[0]*normal[1]-y[1]*normal[0]]
        section_frame=list(coordinates.value)+x+y
    body=part.Bodies.Add();body.Name='B40_NativeRim'
    part.MainBody=body
    if rectangle is None:
        profile=sections.circle(doc,body,'B30_Section',section_frame,radius)
        section_measurements={'section_radius_mm':radius,'section_area_mm2':math.pi*radius**2}
    else:
        profile,_=sections.rectangle(doc,body,'B30_Section',section_frame,width,thickness)
        section_measurements={'section_width_mm':width,'section_thickness_mm':thickness,
                              'half_thickness_mm':thickness/2,'section_area_mm2':width*thickness}
    feature=sections.sweep(doc,body,profile,guide,'B40_NativeSweep')
    endpoints={'end_sections':_circle_end_sections(doc,reference,support,radius)} if rectangle is None else {}
    measured=spa.GetMeasurable(part.CreateReferenceFromObject(feature))
    return {'volume_mm3':measured.Volume*1e9,'area_mm2':measured.Area*1e6,
            'guide_length_mm':length,'section_frame':section_frame,**section_measurements,**endpoints,
            'source_guide_length_mm':source_length,'start_fraction':start_fraction,'end_fraction':end_fraction,
            'expected_volume_mm3':section_measurements['section_area_mm2']*length}
