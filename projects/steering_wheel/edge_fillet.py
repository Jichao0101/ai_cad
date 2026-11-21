"""B80显式直边的最小传播圆角；不推断CAE加料或冻结区规则。"""
import math
from .datum import vector


def create(doc,parameters):
    import pythoncom,win32com.client
    radius=parameters['radius_mm'];ends=parameters['edge_endpoints_mm']
    if isinstance(radius,bool) or not isinstance(radius,(int,float)) or not math.isfinite(radius) or radius<=0:
        raise ValueError('Fillet radius must be positive finite millimetres')
    if len(ends)!=2:raise ValueError('Fillet requires two explicit global edge endpoints')
    ends=[vector(point) for point in ends];expected_length=math.dist(*ends)
    if expected_length<1e-6:raise ValueError('Fillet edge endpoints must be distinct')
    part=doc.Part;body=part.MainBody;spa=doc.GetWorkbench('SPAWorkbench')
    selection=doc.Selection;selection.Clear();selection.Add(body)
    try:
        selection.Search('Topology.CGMEdge,sel')
        references=[selection.Item2(i).Reference for i in range(1,selection.Count2+1)]
    finally:selection.Clear()
    candidates=[]
    for reference in references:
        measured=spa.GetMeasurable(reference)
        if abs(measured.Length-expected_length)>1e-6:continue
        points=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPointsOnCurve'),0,1,0,points)
        actual=[list(points.value[:3]),list(points.value[6:9])]
        if min(max(math.dist(a,b) for a,b in zip(actual,order)) for order in [ends,ends[::-1]])<=1e-6:
            candidates.append((reference,actual))
    if len(candidates)!=1:raise ValueError('Expected one matching straight edge; found '+str(len(candidates)))
    reference,actual=candidates[0]
    before=spa.GetMeasurable(part.CreateReferenceFromObject(body)).Volume*1e9
    name='B80_EdgeFillet_'+str(body.Shapes.Count+1)
    part.InWorkObject=body
    # 本机类型库CatFilletEdgePropagation：0=minimal，1=tangency；仅处理显式边。
    feature=part.ShapeFactory.AddNewEdgeFilletWithConstantRadius(reference,0,radius)
    feature.Name=name;part.Update()
    value=feature.Radius.Value
    if not math.isfinite(value) or abs(value-radius)>1e-8:raise ValueError('Native fillet radius differs from requested value')
    measured=spa.GetMeasurable(part.CreateReferenceFromObject(body));after=measured.Volume*1e9
    return {'radius_mm':value,'volume_mm3':after,'area_mm2':measured.Area*1e6,
            'input_volume_mm3':before,'removed_volume_mm3':before-after,'feature_name':name,
            'selected_edge_endpoints_mm':actual,'edge_reference':reference.DisplayName,'propagation':'minimal'}
