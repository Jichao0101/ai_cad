"""圆辐板解析体积、改半径恢复、重开后直接编辑草图半径与Pad。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime,baffle,cad_frame


def main():
    import win32com.client
    root=Path(__file__).resolve().parents[1]
    output=root/'runs'/datetime.now().strftime('steering-round-baffle-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['parameters']['radius_mm']={'default':30,'min':20,'max':40,'unit':'mm'}
    step=definition['steps'][1];step.pop('check');step['parameters'].pop('outline')
    step['parameters']['radius_mm']={'parameter':'radius_mm'}
    folder,state=runtime.start(definition,{},output)
    assert state['status']=='completed',state.get('error')
    before=state['outputs']['baffle_part']['measurements']
    assert abs(before['volume_mm3']-math.pi*30**2*8.4)<1e-5
    basis=dict(state['outputs']['basis'])
    state=runtime.resume(folder,state['revision'],{'radius_mm':32})
    assert state['status']=='completed',state.get('error')
    assert state['outputs']['basis']==basis
    after=state['outputs']['baffle_part']['measurements']
    assert after['radius_mm']==32 and abs(after['volume_mm3']-math.pi*32**2*8.4)<1e-5
    app=win32com.client.GetActiveObject('CATIA.Application')
    doc=app.Documents.Open(str(folder/state['outputs']['baffle_part']['file']))
    assert baffle.measure(doc)==after
    sketch=doc.Part.MainBody.Sketches.Item('B20_Outline')
    frame=cad_frame.read(sketch)
    sketch.OpenEdition()
    try:sketch.GeometricElements.Item('B20_Circle').SetData(0.0,0.0,35.0)
    finally:sketch.CloseEdition()
    doc.Part.MainBody.Shapes.Item('B20_Thickness').FirstLimit.Dimension.Value=10
    doc.Part.Update()
    edited=baffle.measure(doc)
    assert edited['radius_mm']==35 and edited['thickness_mm']==10
    assert abs(edited['volume_mm3']-math.pi*35**2*10)<1e-5
    doc.SaveAs(str(output/'EditableRoundBaffle.CATPart'))
    doc.Activate();app.Visible=True;app.ActiveWindow.ActiveViewer.Reframe()
    report={'fixture_only':True,'passed':True,'before':before,'after':after,'edited':edited,
            'saved_frame':frame,'datum_asset_unchanged':True,'run_directory':str(folder)}
    (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
