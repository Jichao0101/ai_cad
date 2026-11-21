"""在明确Body/特征范围内识别唯一圆柱面，读取管柱轴线。"""
from .datum import unit,dot,vector
from .inputs import resolve_object


def extract(app,path,object_path,positive_direction):
    import pythoncom,win32com.client
    positive=unit(positive_direction)
    doc=app.Documents.Open(str(path))
    try:
        scope=resolve_object(doc.Part,object_path)
        selection=doc.Selection;selection.Clear();selection.Add(scope)
        try:
            selection.Search('Topology.CGMFace,sel')
            references=[selection.Item2(i).Reference for i in range(1,selection.Count2+1)]
        finally:selection.Clear()
        spa=doc.GetWorkbench('SPAWorkbench');candidates=[]
        for reference in references:
            measured=spa.GetMeasurable(reference)
            if measured.GeometryName==4:candidates.append((reference,measured))
        if len(candidates)!=1:raise ValueError('Column scope requires exactly one cylindrical face; found '+str(len(candidates)))
        reference,measured=candidates[0]
        axis=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
        points=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetAxis'),0,1,0,axis)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPointsOnAxis'),0,1,0,points)
        direction=unit(list(axis.value));sense=dot(direction,positive)
        if abs(sense)<1e-8:raise ValueError('Positive direction does not determine the cylinder axis sense')
        if sense<0:direction=[-v for v in direction]
        return {'point_mm':vector(list(points.value)[:3]),'direction':direction,'radius_mm':measured.Radius,
                'scope':object_path,'face_reference':reference.DisplayName}
    finally:doc.Close()
