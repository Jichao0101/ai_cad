"""在当前CATIA验证扫掠和桥接原生操作；测试件不是方向盘成品。"""
import json, math, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import sections,cad_frame


def volume(doc, feature):
    return doc.GetWorkbench('SPAWorkbench').GetMeasurable(doc.Part.CreateReferenceFromObject(feature)).Volume*1e9


def main():
    import win32com.client
    app=win32com.client.GetActiveObject('CATIA.Application')
    root=Path(__file__).resolve().parents[1]/'runs'/datetime.now().strftime('steering-sections-%Y%m%d-%H%M%S-%f')
    root.mkdir(parents=True)
    report={'fixture_only':True,'ds_status':'not_evaluated','operations':{}}
    for operation in ['sweep','curved_sweep','bridge']:
        doc=app.Documents.Add('Part');part=doc.Part;body=part.MainBody
        frame=[100,0,0,-1,0,0,0,0,1] if operation=='curved_sweep' else [0,0,0,1,0,0,0,1,0]
        first=sections.circle(doc,body,'StartSection',frame,5)
        if operation=='bridge':
            end=sections.circle(doc,body,'EndSection',[0,0,40,1,0,0,0,1,0],5)
            closing=part.HybridBodies.Add();closing.Name='ClosingPoints'
            points=[]
            for z in [0,40]:
                point=part.HybridShapeFactory.AddNewPointCoord(5,0,z)
                closing.AppendHybridShape(point);points.append(point)
            part.Update()
            guide=part.HybridShapeFactory.AddNewLinePtPt(part.CreateReferenceFromObject(points[0]),part.CreateReferenceFromObject(points[1]))
            closing.AppendHybridShape(guide);part.Update()
            feature=sections.bridge(doc,body,[first,end],points,'TestBridge',guides=[guide])
        elif operation=='curved_sweep':
            guide=body.Sketches.Add(part.CreateReferenceFromObject(part.OriginElements.PlaneXY))
            guide.Name='QuarterCircleGuide'
            cad_frame.set_verified(guide,(0,0,0,1,0,0,0,1,0))
            factory=guide.OpenEdition()
            arc=factory.CreateCircle(0,0,100,0,math.pi/2)
            arc.StartPoint=factory.CreatePoint(100,0)
            arc.EndPoint=factory.CreatePoint(0,100)
            guide.CloseEdition();part.Update()
            feature=sections.sweep(doc,body,first,guide,'CurvedSweep')
        else:
            container=part.HybridBodies.Add();container.Name='Guide'
            f=part.HybridShapeFactory
            p=f.AddNewPointCoord(0,0,0);container.AppendHybridShape(p)
            line=f.AddNewLinePtDir(part.CreateReferenceFromObject(p),f.AddNewDirectionByCoord(0,0,1),0,40,False)
            container.AppendHybridShape(line);part.Update()
            feature=sections.sweep(doc,body,first,line,'TestSweep')
        name=feature.Name
        before=volume(doc,feature)
        path=root/(operation+'.CATPart')
        doc.SaveAs(str(path));doc.Close()
        doc=app.Documents.Open(str(path))
        after=volume(doc,doc.Part.MainBody.Shapes.Item(name))
        saved_frame=cad_frame.read(doc.Part.MainBody.Sketches.Item('StartSection'))
        assert all(abs(a-b)<1e-7 for a,b in zip(frame,saved_frame))
        expected=math.pi*25*(100*math.pi/2 if operation=='curved_sweep' else 40)
        report['operations'][operation]={'before_mm3':before,'reopened_mm3':after,'expected_mm3':expected,
            'saved_frame':saved_frame,'analytic_error_mm3':after-expected,'analytic_passed':abs(after-expected)<.001,
            'persistence_passed':abs(before-after)<.000001,'file':str(path)}
        if operation!='bridge': doc.Close()
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    report['passed']=all(v['analytic_passed'] and v['persistence_passed'] for v in report['operations'].values())
    (root/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['passed']: raise SystemExit(1)


if __name__=='__main__':main()
