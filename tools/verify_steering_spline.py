"""显式样条段夹具的原生几何、位置及保存重开测试。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import spline_segment,cad_frame


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]/'runs'/datetime.now().strftime('steering-spline-%Y%m%d-%H%M%S-%f')
    root.mkdir(parents=True)
    app=win32com.client.GetActiveObject('CATIA.Application');doc=app.Documents.Add('Part')
    basis={'origin_mm':[10,20,30],'x':[1,0,0],'y':[0,1,0],'z':[0,0,1]}
    parameters={'guide_points_mm':[[0,0,0],[0,0,20],[10,0,50],[30,0,80]],
        'profile_x':[1,0,0],'profile_y':[0,1,0],'section_radius_mm':3}
    measurements=spline_segment.create(doc,basis,parameters)
    path=root/'SplineFixture.CATPart';doc.SaveAs(str(path));doc.Close()
    doc=app.Documents.Open(str(path));part=doc.Part
    volume=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody.Shapes.Item('B40_Sweep'))).Volume*1e9
    frame=cad_frame.read(part.MainBody.Sketches.Item('B30_Section'))
    assert all(abs(a-b)<1e-7 for a,b in zip(frame,[10,20,30,1,0,0,0,1,0]))
    assert abs(volume-measurements['volume_mm3'])<1e-6
    error=volume-measurements['expected_volume_mm3']
    report={'fixture_only':True,'measurements':measurements,'analytic_error_mm3':error,
        'analytic_passed':abs(error)<.001,'persistence_passed':True,'saved_frame':frame,'file':str(path)}
    (root/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    doc.Activate();app.Visible=True;app.ActiveWindow.ActiveViewer.Reframe()
    print(json.dumps(report),flush=True)
    if not report['analytic_passed']:raise SystemExit(1)


if __name__=='__main__':main()
