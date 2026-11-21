"""读取具名平面几何；不将非平面底罩拟合为平面。"""
from .datum import unit,vector,dot
from .inputs import resolve_object


def extract(app,path,object_path,positive_normal):
    import pythoncom,win32com.client
    positive=unit(positive_normal)
    doc=app.Documents.Open(str(path))
    try:
        surface=resolve_object(doc.Part,object_path)
        measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(surface))
        if measured.GeometryName!=7:raise ValueError('Expected an explicitly bound planar surface; curved projection is not implemented')
        values=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
        measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetPlane'),0,1,0,values)
        data=list(values.value);x=vector(data[3:6]);y=vector(data[6:9])
        normal=unit([x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]])
        sense=dot(normal,positive)
        if abs(sense)<1e-8:raise ValueError('Positive normal reference is perpendicular to the plane normal')
        if sense<0:normal=[-v for v in normal]
        return {'point_mm':vector(data[:3]),'normal':normal,'scope':object_path}
    finally:doc.Close()


def point_distance(app,path,object_path,coordinates):
    """检查投影是否落在真实面上，避免只验证无限延伸的底层平面。"""
    doc=app.Documents.Open(str(path))
    try:
        part=doc.Part;surface=resolve_object(part,object_path)
        support=part.HybridBodies.Add()
        point=part.HybridShapeFactory.AddNewPointCoord(*vector(coordinates))
        support.AppendHybridShape(point);part.Update()
        measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(surface))
        return float(measured.GetMinimumDistance(part.CreateReferenceFromObject(point)))
    finally:doc.Close()
