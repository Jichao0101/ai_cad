"""实际CAD分支恢复测试：改变轮圈截面，基准与辐板资产保留。"""
import json,math,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from projects.steering_wheel import runtime


def main():
    root=Path(__file__).resolve().parents[1]
    folder=root/'runs'/datetime.now().strftime('steering-branches-%Y%m%d-%H%M%S-%f')
    definition=runtime.read(root/'tests/fixtures/steering_baffle_flow.json')
    definition['steps'][1].pop('check')
    definition['parameters']['section_radius_mm']={'default':4,'min':3,'max':6,'unit':'mm'}
    definition['steps'].append({'id':'rim','operation':'rim_segment','inputs':{'basis':'basis'},'output':'rim_part',
        'parameters':{'guide_radius_mm':100,'section_radius_mm':{'parameter':'section_radius_mm'},'start_angle_rad':0,'end_angle_rad':math.pi/2},
        'check':{'measurement':'volume_mm3','minimum':10000,'source':'branch recovery fixture, not DS'}})
    run,initial=runtime.start(definition,{},folder)
    assert initial['status']=='check_failed',initial
    preserved={k:dict(initial['outputs'][k]) for k in ['basis','baffle_part']}
    # 改无关的辐板参数不能跳过仍失败的轮圈检查。
    still_failed=runtime.resume(run,initial['revision'],{'thickness_mm':9})
    assert still_failed['status']=='check_failed',still_failed
    preserved['baffle_part']=dict(still_failed['outputs']['baffle_part'])
    updated=runtime.resume(run,still_failed['revision'],{'section_radius_mm':5})
    assert updated['status']=='completed',updated
    for key,value in preserved.items():
        assert updated['outputs'][key]==value
        assert runtime.digest(run/value['file'])==value['sha256']
    assert updated['recovery']['execute']==['rim']
    clean_run,clean=runtime.start(definition,{'thickness_mm':9,'section_radius_mm':5},folder)
    assert clean['status']=='completed',clean
    assert clean['outputs']['rim_part']['measurements']==updated['outputs']['rim_part']['measurements']
    measured=updated['outputs']['rim_part']['measurements']
    assert abs(measured['volume_mm3']-measured['expected_volume_mm3'])<.001
    report={'fixture_only':True,'passed':True,'run':str(run),'clean_run':str(clean_run),'retained':updated['recovery']['retained'],'measurements':measured}
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
