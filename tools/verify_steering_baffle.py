"""使用明确标注的测试轮廓验证B20操作，不作为真实骨架工程验收。"""
import json
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import baffle,datum,cad_frame


def main():
    import win32com.client
    app=win32com.client.GetActiveObject('CATIA.Application')
    root=Path(__file__).resolve().parents[1]/'runs'/datetime.now().strftime('steering-baffle-%Y%m%d-%H%M%S-%f')
    root.mkdir(parents=True)
    path=root/'B20_TestFixture.CATPart'
    points=[[-30,-20],[30,-20],[30,20],[-30,20]]
    basis=datum.solve({'origin_rule':'sor_3_9','column_point':[0,0,0],
        'column_direction':[0,-1,0],'symmetry_point':[0,0,0],'symmetry_normal':[0,0,1],
        'outer_3':[10,0,100],'outer_9':[10,0,-100],
        'bottom_point':[0,20,0],'bottom_normal':[0,1,0]})
    frame=basis['sketch_frame']
    area=baffle.validate_profile(points,frame,8.4)
    doc=app.Documents.Add('Part')
    datum.create(doc,basis)
    pad=baffle.create(doc,points,frame,8.4)
    results={'initial':baffle.measure(doc)}
    pad.FirstLimit.Dimension.Value=10.0
    doc.Part.Update()
    results['updated']=baffle.measure(doc)
    doc.SaveAs(str(path))
    doc.Close()
    doc=app.Documents.Open(str(path))
    results['reopened']=baffle.measure(doc)
    saved_frame=cad_frame.read(doc.Part.MainBody.Sketches.Item('B20_Outline'))
    assert all(abs(a-b)<1e-7 for a,b in zip(frame,saved_frame))
    for phase,thickness in [('initial',8.4),('updated',10),('reopened',10)]:
        assert abs(results[phase]['thickness_mm']-thickness)<1e-6
        assert abs(results[phase]['volume_mm3']-area*thickness)<.001
    doc.Activate()
    app.Visible=True
    app.ActiveWindow.ActiveViewer.Reframe()
    result={'fixture_only':True,'ds_status':'not_evaluated','basis':basis,'saved_frame':saved_frame,'file':str(path),'results':results,'passed':True}
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
