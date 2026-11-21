"""验证镜像只覆盖指定阶段，其他非对称分支保留。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-mirror-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['parameters']['thickness_mm']['default']=10
    first=definition['steps'][1];first.pop('check')
    first['parameters']['outline']=[[0,0],[10,0],[10,10],[0,10]]
    definition['steps'].extend([
        {'id':'asymmetric','operation':'baffle','inputs':{'basis':'basis'},'output':'asymmetric_part',
         'parameters':{'outline':[[0,20],[10,20],[10,30],[0,30]],'thickness_mm':10}},
        {'id':'mirror','operation':'mirror','inputs':{'basis':'basis','source':'baffle_part'},
         'output':'mirrored_part','parameters':{}},
        {'id':'union','operation':'combine','inputs':{'mirrored':'mirrored_part','asymmetric':'asymmetric_part'},
         'output':'union_part','parameters':{}}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    assert abs(state['outputs']['mirrored_part']['measurements']['volume_mm3']-2000)<1e-6
    assert abs(state['outputs']['union_part']['measurements']['volume_mm3']-3000)<1e-6
    retained=dict(state['outputs']['asymmetric_part'])
    state=runtime.resume(folder,state['revision'],{'thickness_mm':12})
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['asymmetric_part']==retained
    assert state['recovery']['execute']==['baffle','mirror','union']
    assert abs(state['outputs']['mirrored_part']['measurements']['volume_mm3']-2400)<1e-6
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['union_part']['file']))
    part=doc.Part
    measured=doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody))
    reopened=measured.Volume*1e9
    assert abs(reopened-3400)<1e-6
    assert part.FindObjectByName('Stage_mirrored').Shapes.Item('B60_StageMirror').Name=='B60_StageMirror'
    assert part.FindObjectByName('Stage_asymmetric').Shapes.Count==1
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'passed':True,'reopened_volume_mm3':reopened,
            'asymmetric_asset_unchanged':True,'recovery':state['recovery'],'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
