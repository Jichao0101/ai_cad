"""确认绑定、失效和跨进程状态行为；使用无需CAD的基准阶段。"""
import copy,json,tempfile,unittest
from pathlib import Path
from projects.steering_wheel import runtime


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        fixture=runtime.read(Path(__file__).parent/'fixtures/steering_baffle_flow.json')
        first=fixture['steps'][0];first['requires_confirmation']=True
        first['parameters']['bottom_point'][2]={'parameter':'height'}
        other=copy.deepcopy(first);other.update(id='other',output='other_basis',requires_confirmation=False)
        other['parameters']['bottom_point'][2]={'parameter':'other_height'}
        self.definition={'parameters':{'height':{'default':0,'min':0,'max':10},'other_height':{'default':0,'min':0,'max':10}},
                         'steps':[first,other],'max_attempts':4}

    def approve(self,folder,state):
        return runtime.confirm(folder,state['revision'],state['pending_confirmation']['fingerprint'],'test-only reviewer')

    def test_wait_confirm_then_unrelated_change_preserves_approval(self):
        folder,state=runtime.start(self.definition,{},self.root)
        self.assertEqual(state['status'],'waiting_confirmation')
        self.assertEqual(state['completed'],['datum'])
        report=folder/state['pending_confirmation']['report']
        self.assertEqual(runtime.digest(report),state['pending_confirmation']['fingerprint'])
        state=self.approve(folder,state)
        self.assertEqual(state['status'],'completed')
        approval=dict(state['confirmations']['datum'])
        state=runtime.resume(folder,state['revision'],{'other_height':2})
        self.assertEqual(state['status'],'completed')
        self.assertEqual(state['confirmations']['datum'],approval)

    def test_changed_parameter_invalidates_old_confirmation(self):
        folder,state=runtime.start(self.definition,{},self.root)
        old=state['pending_confirmation']['fingerprint']
        state=self.approve(folder,state)
        state=runtime.resume(folder,state['revision'],{'height':2})
        self.assertEqual(state['status'],'waiting_confirmation')
        self.assertNotIn('datum',state['confirmations'])
        self.assertTrue(any(e.get('event')=='confirmation_invalidated' for e in state['events']))
        with self.assertRaisesRegex(ValueError,'fingerprint'):
            runtime.confirm(folder,state['revision'],old,'test-only reviewer')
        self.assertEqual(self.approve(folder,state)['status'],'completed')

    def test_reject_stale_revision_and_duplicate_confirmation(self):
        folder,state=runtime.start(self.definition,{},self.root)
        fingerprint=state['pending_confirmation']['fingerprint']
        with self.assertRaisesRegex(ValueError,'revision'):
            runtime.confirm(folder,state['revision']-1,fingerprint,'test-only reviewer')
        state=self.approve(folder,state)
        with self.assertRaisesRegex(ValueError,'not waiting'):
            runtime.confirm(folder,state['revision'],fingerprint,'test-only reviewer')

    def test_reject_modified_asset_and_report(self):
        for target in ('asset','report'):
            with self.subTest(target=target):
                folder,state=runtime.start(self.definition,{},self.root)
                name=state['outputs']['basis']['file'] if target=='asset' else state['pending_confirmation']['report']
                (folder/name).write_text('modified',encoding='utf-8')
                before=(folder/'state.json').read_bytes()
                with self.assertRaisesRegex(ValueError,'changed'):self.approve(folder,state)
                self.assertEqual((folder/'state.json').read_bytes(),before)

    def test_rule_change_rejects_previous_report(self):
        folder,state=runtime.start(self.definition,{},self.root)
        state['flow']['steps'][0]['parameters']['bottom_point']=[0,0,3]
        (folder/'state.json').write_text(json.dumps(state),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Flow version changed'):self.approve(folder,state)

    def test_check_failure_cannot_offer_confirmation(self):
        folder,state=runtime.start(self.definition,{},self.root)
        state.pop('pending_confirmation')
        step=copy.deepcopy(self.definition['steps'][0])
        step['check']={'measurement':'distance','minimum':2,'source':'fixture only'}
        state['outputs']['basis']['measurements']['distance']=1
        self.assertFalse(runtime.stage_gate(folder,state,step))
        self.assertEqual(state['status'],'check_failed')
        self.assertNotIn('pending_confirmation',state)
        with self.assertRaisesRegex(ValueError,'not waiting'):
            runtime.confirm(folder,state['revision'],'invalid','test-only reviewer')


if __name__=='__main__':unittest.main()
