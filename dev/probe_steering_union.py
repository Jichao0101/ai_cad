"""验证跨Part原生复制、布尔合并及重开后编辑。仅使用合成夹具。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import win32com.client
from projects.steering_wheel import baffle

root=Path(__file__).resolve().parents[1]/'runs'/datetime.now().strftime('steering-union-%Y%m%d-%H%M%S-%f')
root.mkdir(parents=True)
app=win32com.client.GetActiveObject('CATIA.Application')
target=app.Documents.Add('Part')
part=target.Part
copied=[]
for i,x in enumerate([0,5]):
    source=app.Documents.Add('Part')
    baffle.create(source,[[0,0],[10,0],[10,10],[0,10]],[x,0,0,1,0,0,0,1,0],10)
    source.Part.MainBody.Name='Branch'+str(i)
    source.SaveAs(str(root/('Source'+str(i)+'.CATPart')))
    selection=source.Selection
    selection.Clear()
    selection.Add(source.Part.HybridBodies.Item(1))
    selection.Add(source.Part.MainBody)
    selection.Copy()
    target.Activate()
    before=part.Bodies.Count
    dest=target.Selection
    dest.Clear();dest.Add(part);dest.PasteSpecial('CATPrtCont');dest.Clear()
    part.Update()
    assert part.Bodies.Count==before+1
    copied.append(part.Bodies.Item(part.Bodies.Count))
    source.Close()
    print('copied',i,flush=True)
part.InWorkObject=part.MainBody
for body in copied:
    feature=part.ShapeFactory.AddNewAdd(body)
    part.Update()
def volume():
    return target.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
initial=volume()
path=root/'Union.CATPart'
target.SaveAs(str(path));target.Close()
target=app.Documents.Open(str(path));part=target.Part
reopened=volume()
pad=part.FindObjectByName('Branch0').Shapes.Item('B20_Thickness')
pad.FirstLimit.Dimension.Value=12
part.Update()
updated=volume()
target.Save()
report={'initial_volume_mm3':initial,'reopened_volume_mm3':reopened,'updated_volume_mm3':updated,
        'passed':abs(initial-1500)<1e-5 and abs(reopened-1500)<1e-5 and abs(updated-1700)<1e-5,'file':str(path)}
(root/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
app.Visible=True;target.Activate();app.ActiveWindow.ActiveViewer.Reframe()
print(json.dumps(report),flush=True)
if not report['passed']:raise SystemExit(1)
