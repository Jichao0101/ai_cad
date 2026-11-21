"""开发探针：比较原生Loft解析曲面识别设置，不修改工程检查限值。"""
import sys,json,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import sections
import win32com.client

app=win32com.client.GetActiveObject('CATIA.Application')
results=[]
for detection in [0,1,2]:
    doc=app.Documents.Add('Part')
    try:
        part=doc.Part;body=part.MainBody
        profiles=[sections.circle(doc,body,'Profile'+str(z),[0,0,z,1,0,0,0,1,0],5) for z in [0,40]]
        points=[];container=part.HybridBodies.Add()
        for z in [0,40]:
            point=part.HybridShapeFactory.AddNewPointCoord(5,0,z);container.AppendHybridShape(point);points.append(point)
        part.Update()
        loft=sections.bridge(doc,body,profiles,points,'Loft')
        loft.HybridShape.CanonicalDetection=detection
        part.Update()
        value=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(loft)).Volume*1e9
        results.append({'canonical_detection':detection,'volume_mm3':value,'error_mm3':value-math.pi*25*40})
    except Exception as error:
        results.append({'canonical_detection':detection,'error':str(error)})
    finally:
        doc.Close()
print(json.dumps(results),flush=True)
