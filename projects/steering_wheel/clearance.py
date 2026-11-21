"""同一设计全局坐标下两个阶段实体的CATIA最小距离测量。"""
import math
from .inputs import resolve_object


def measure(app,first_path,second_path,object_paths=(None,None)):
    import pythoncom,win32com.client
    documents=[]
    try:
        for path in (first_path,second_path):documents.append(app.Documents.Open(str(path)))
        references=[];objects=[]
        for doc,object_path in zip(documents,object_paths):
            if object_path is not None:
                feature=resolve_object(doc.Part,object_path)
                objects.append({'path':object_path,'feature':feature.Name})
            else:
                body=doc.Part.MainBody
                if body.Shapes.Count<1:raise ValueError('Clearance input has no solid feature; supply an explicit object binding for surface inputs')
                feature=body.Shapes.Item(body.Shapes.Count)
                objects.append({'body':body.Name,'feature':feature.Name})
            references.append(doc.Part.CreateReferenceFromObject(feature))
        measurable=documents[0].GetWorkbench('SPAWorkbench').GetMeasurable(references[0])
        distance=float(measurable.GetMinimumDistance(references[1]))
        points=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
        measurable._oleobj_.Invoke(measurable._oleobj_.GetIDsOfNames('GetMinimumDistancePoints'),0,1,0,references[1]._oleobj_,points)
        coordinates=list(points.value)[:6]
        if not math.isfinite(distance) or distance<0 or any(not math.isfinite(v) for v in coordinates):
            raise ValueError('CATIA returned invalid clearance measurements')
        separation=math.sqrt(sum((a-b)**2 for a,b in zip(coordinates[:3],coordinates[3:])))
        if abs(separation-distance)>1e-5:raise ValueError('Closest points disagree with minimum distance')
        return {'minimum_distance_mm':distance,'first_point_mm':coordinates[:3],'second_point_mm':coordinates[3:],
                'first_object':objects[0],'second_object':objects[1]}
    finally:
        for doc in reversed(documents):doc.Close()
