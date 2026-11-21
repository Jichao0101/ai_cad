"""验证组合阶段的分支恢复、体积与重开后原生参数编辑。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-combine-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['parameters']['thickness_mm']['default']=10
    first=definition['steps'][1]
    first.pop('check')
    first['parameters']['outline']=[[0,0],[10,0],[10,10],[0,10]]
    definition['steps'].extend([
        {'id':'second','operation':'baffle','inputs':{'basis':'basis'},'output':'second_part',
         'parameters':{'outline':[[5,0],[15,0],[15,10],[5,10]],'thickness_mm':10}},
        {'id':'union','operation':'combine','inputs':{'first':'baffle_part','second':'second_part'},
         'output':'union_part','parameters':{}}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    initial=state['outputs']['union_part']['measurements']['volume_mm3']
    retained=dict(state['outputs']['second_part'])
    assert abs(initial-1500)<1e-5
    state=runtime.resume(folder,state['revision'],{'thickness_mm':12})
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['second_part']==retained
    assert state['recovery']['execute']==['baffle','union']
    rebuilt=state['outputs']['union_part']['measurements']['volume_mm3']
    assert abs(rebuilt-1700)<1e-5
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['union_part']['file']))
    part=doc.Part
    def volume():
        return doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
    reopened=volume()
    assert abs(reopened-1700)<1e-5
    part.FindObjectByName('Stage_first').Shapes.Item('B20_Thickness').FirstLimit.Dimension.Value=11
    part.Update()
    edited=volume()
    assert abs(edited-1600)<1e-5
    # 编辑演示另存，避免修改执行器正在追踪的阶段资产。
    doc.SaveAs(str(output/'EditableUnion.CATPart'))
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'initial_volume_mm3':initial,'rebuilt_volume_mm3':rebuilt,
            'reopened_volume_mm3':reopened,'edited_volume_mm3':edited,'recovery':state['recovery'],
            'retained_branch_unchanged':True,'passed':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
