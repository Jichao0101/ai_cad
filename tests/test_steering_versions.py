"""跨进程续跑不得在原运行内替换规则、预算或执行代码。"""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from projects.steering_wheel import runtime


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        first=runtime.read(Path(__file__).parent/'fixtures/steering_baffle_flow.json')['steps'][0]
        first['parameters']['bottom_point'][2]={'parameter':'height'}
        self.definition={'steps':[first],'parameters':{'height':{'default':0,'min':0,'max':10}},'max_attempts':3}

    def test_resume_rejects_changed_rules_budget_and_parameter_range(self):
        for kind in ('checks','budget','range'):
            with self.subTest(kind=kind):
                folder,state=runtime.start(copy.deepcopy(self.definition),{},self.root)
                if kind=='checks':state['flow']['steps'][0]['checks']=[{'measurement':'v','minimum':0}]
                elif kind=='budget':state['flow']['max_attempts']=100
                else:state['flow']['parameters']['height']['max']=100
                path=folder/'state.json';path.write_text(json.dumps(state),encoding='utf-8')
                before=path.read_bytes()
                with self.assertRaisesRegex(ValueError,'Flow version'):
                    runtime.resume(folder,state['revision'],{'height':2})
                self.assertEqual(path.read_bytes(),before)

    def test_code_change_and_unsigned_checkpoint_rejected(self):
        folder,state=runtime.start(copy.deepcopy(self.definition),{},self.root)
        before=(folder/'state.json').read_bytes()
        with patch.object(runtime,'execution_signature',return_value='new-code'):
            with self.assertRaisesRegex(ValueError,'code version'):
                runtime.resume(folder,state['revision'],{'height':2})
        self.assertEqual((folder/'state.json').read_bytes(),before)
        state.pop('flow_signature')
        (folder/'state.json').write_text(json.dumps(state),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'flow signature'):
            runtime.resume(folder,state['revision'],{'height':2})

    def test_input_retry_validates_before_loading(self):
        folder,state=runtime.start(copy.deepcopy(self.definition),{},self.root)
        state.update(status='needs_input',completed=[])
        state['flow']['external_objects']={'replacement':{}}
        path=folder/'state.json';path.write_text(json.dumps(state),encoding='utf-8')
        before=path.read_bytes()
        with patch.object(runtime,'load_inputs') as loader:
            with self.assertRaisesRegex(ValueError,'Flow version'):runtime.retry_inputs(folder,state['revision'])
            loader.assert_not_called()
        self.assertEqual(path.read_bytes(),before)

    def test_confirmation_rejects_changes_to_future_steps(self):
        definition=copy.deepcopy(self.definition)
        definition['steps'][0]['requires_confirmation']=True
        later=copy.deepcopy(definition['steps'][0]);later.update(id='later',output='later_basis',requires_confirmation=False)
        definition['steps'].append(later)
        folder,state=runtime.start(definition,{},self.root)
        state['flow']['steps'][1]['parameters']['bottom_point']=[0,0,99]
        path=folder/'state.json';path.write_text(json.dumps(state),encoding='utf-8')
        before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'Flow version'):
            runtime.confirm(folder,state['revision'],state['pending_confirmation']['fingerprint'],'test reviewer')
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
