"""实测原生减料、检查失败恢复、原件保留及重开后的参数编辑。"""
import json,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-subtract-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['parameters']={'depth_mm':{'default':5,'min':1,'max':9,'unit':'mm'}}
    stock=definition['steps'][1]
    stock.pop('check')
    stock['parameters']={'outline':[[0,0],[10,0],[10,10],[0,10]],'thickness_mm':10}
    definition['steps'].extend([
        {'id':'tool','operation':'baffle','inputs':{'basis':'basis'},'output':'tool_part',
         'parameters':{'outline':[[5,0],[15,0],[15,10],[5,10]],'thickness_mm':{'parameter':'depth_mm'}}},
        {'id':'slot','operation':'subtract','inputs':{'tool':'tool_part','stock':'baffle_part'},
         'output':'slotted_part','parameters':{},
         'check':{'measurement':'removed_volume_mm3','minimum':350,'source':'recovery fixture only, not DS'}}])
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='check_failed',state.get('error')
    initial=state['outputs']['slotted_part']['measurements']
    assert abs(initial['removed_volume_mm3']-250)<1e-5
    retained=dict(state['outputs']['baffle_part'])
    state=runtime.resume(folder,state['revision'],{'depth_mm':8})
    assert state['status']=='completed',state.get('error')
    assert state['recovery']['execute']==['tool','slot']
    assert state['outputs']['baffle_part']==retained
    assert runtime.digest(folder/retained['file'])==retained['sha256']
    measured=state['outputs']['slotted_part']['measurements']
    assert abs(measured['removed_volume_mm3']-400)<1e-5
    clean_folder,clean=runtime.start(definition,{'depth_mm':8},output)
    assert clean['status']=='completed',clean.get('error')
    assert abs(clean['outputs']['slotted_part']['measurements']['volume_mm3']-measured['volume_mm3'])<1e-5
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['slotted_part']['file']))
    part=doc.Part
    def volume():
        return doc.GetWorkbench('SPAWorkbench').GetMeasurable(part.CreateReferenceFromObject(part.MainBody)).Volume*1e9
    reopened=volume()
    assert abs(reopened-600)<1e-5
    part.FindObjectByName('Stage_tool').Shapes.Item('B20_Thickness').FirstLimit.Dimension.Value=7
    part.Update()
    edited=volume()
    assert abs(edited-650)<1e-5
    doc.SaveAs(str(output/'EditableSubtraction.CATPart'))
    app.Visible=True;doc.Activate();app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'initial':initial,'updated':measured,'reopened_volume_mm3':reopened,
            'edited_volume_mm3':edited,'recovery':state['recovery'],'stock_unchanged':True,
            'clean_build_matches':True,'passed':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
