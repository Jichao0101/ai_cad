import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from projects.steering_wheel import runtime


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        first=runtime.read(Path(__file__).parent/'fixtures/steering_baffle_flow.json')['steps'][0]
        second=copy.deepcopy(first);second.update(id='second',output='second_basis',inputs={'upstream':'basis'})
        self.definition={'steps':[first,second],'parameters':{},'max_attempts':3}
        self.solve=runtime.datum.solve

    def failed_run(self):
        calls=0
        def fail_second(parameters):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('injected environment failure')
            return self.solve(parameters)
        with patch.object(runtime.datum,'solve',side_effect=fail_second):
            folder,state=runtime.start(self.definition,{},self.root)
        self.assertEqual(state['status'],'execution_error')
        self.assertEqual(state['completed'],['datum'])
        return folder,state

    def test_same_run_retains_completed_assets(self):
        folder,state=self.failed_run();original=dict(state['outputs']['basis'])
        state=runtime.retry(folder,state['revision'])
        self.assertEqual(state['status'],'completed')
        self.assertEqual(state['outputs']['basis'],original)
        self.assertEqual(state['recovery']['execute'],['second'])
        self.assertEqual(len(state['attempts']),2)
        self.assertTrue(any(e.get('event')=='execution_error' for e in state['events']))
        self.assertTrue(any(e.get('event')=='technical_retry' for e in state['events']))

    def test_repeated_faults_exhaust_original_budget(self):
        folder,state=self.failed_run()
        with patch.object(runtime.datum,'solve',side_effect=RuntimeError('still unavailable')):
            for _ in range(2):state=runtime.retry(folder,state['revision'])
            self.assertEqual(len(state['attempts']),3)
            before=(folder/'state.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'budget'):runtime.retry(folder,state['revision'])
            self.assertEqual((folder/'state.json').read_bytes(),before)

    def test_stale_revision_code_change_or_modified_asset_rejected(self):
        folder,state=self.failed_run()
        with self.assertRaisesRegex(ValueError,'revision'):runtime.retry(folder,state['revision']-1)
        with patch.object(runtime,'execution_signature',return_value='different'):
            with self.assertRaisesRegex(ValueError,'code version'):runtime.retry(folder,state['revision'])
        (folder/state['outputs']['basis']['file']).write_text('edited',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'asset changed'):runtime.retry(folder,state['revision'])

    def test_completed_run_cannot_use_technical_retry(self):
        folder,state=runtime.start(self.definition,{},self.root)
        with self.assertRaisesRegex(ValueError,'execution_error'):runtime.retry(folder,state['revision'])

    def test_changed_flow_cannot_reuse_checkpoint(self):
        folder,state=self.failed_run()
        state['flow']['steps'][1]['parameters']['bottom_point']=[0,0,50]
        (folder/'state.json').write_text(json.dumps(state),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Flow version'):runtime.retry(folder,state['revision'])


if __name__=='__main__':unittest.main()
