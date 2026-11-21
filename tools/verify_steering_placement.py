"""验证原生刚体定位、保存重开及直接修改目标轴系。"""
import json,math,shutil,sys,uuid
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle,placement


def main():
    import pythoncom,win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-placement-%Y%m%d-%H%M%S-%f');output.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    baffle.create(doc,[[0,0],[10,0],[10,20],[0,20]],[0,0,0,1,0,0,0,1,0],30)
    source=output/'PlatformInput.CATPart';doc.SaveAs(str(source));doc.Close();source_hash=runtime.digest(source)
    working=output/('Placed_'+uuid.uuid4().hex+'.CATPart');shutil.copyfile(source,working)
    doc=app.Documents.Open(str(working))
    source_frame={'origin_mm':[0,0,0],'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]}
    target_frame={'origin_mm':[100,200,300],'x':[0,1,0],'y':[-1,0,0],'z':[0,0,1]}
    try:
        initial=placement.create(doc,source_frame,target_frame);doc.Save()
    finally:doc.Close()
    doc=app.Documents.Open(str(working))
    try:
        part=doc.Part
        def measure():
            measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody))
            xyz=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*3)
            measured._oleobj_.Invoke(measured._oleobj_.GetIDsOfNames('GetCOG'),0,1,0,xyz)
            return {'volume_mm3':measured.Volume*1e9,'cog_mm':list(xyz.value)}
        reopened=measure();assert math.dist(reopened['cog_mm'],[90,205,315])<1e-6
        part.AxisSystems.Item(initial['target_axis_name']).PutOrigin((110.,200.,300.));part.Update()
        edited=measure();assert math.dist(edited['cog_mm'],[100,205,315])<1e-6
        assert abs(edited['volume_mm3']-6000)<1e-6
        assert part.MainBody.Shapes.Item('B20_Thickness').Name=='B20_Thickness'
        doc.SaveAs(str(output/'EditedPlacement.CATPart'))
    finally:doc.Close()
    assert runtime.digest(source)==source_hash
    report={'fixture_only':True,'passed':True,'initial':initial,'reopened':reopened,'edited':edited,'source_unchanged':True}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({'report':str(output/'result.json'),**report}),flush=True)


if __name__=='__main__':main()
