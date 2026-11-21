"""多项检查规则、测量错误及可追溯报告。"""
import copy,tempfile,unittest
from pathlib import Path
from projects.steering_wheel import checks,runtime


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.step={'id':'part','output':'part_asset','checks':[
            {'id':'volume','measurement':'volume_mm3','minimum':900,'maximum':1100,
             'unit':'mm3','source':'fixture only','version':'1'},
            {'id':'height','measurement':'thickness_mm','maximum':10,
             'unit':'mm','source':'fixture only','version':'1'}]}

    def test_all_results_including_upper_bound_failure(self):
        results=checks.evaluate(self.step,{'volume_mm3':1000,'thickness_mm':12})
        self.assertEqual([r['passed'] for r in results],[True,False])
        self.assertEqual(results[1]['actual'],12)
        self.assertTrue(all(r['passed'] for r in checks.evaluate(self.step,{'volume_mm3':900,'thickness_mm':10})))

    def test_invalid_measurements_are_technical_errors(self):
        for value in (None,True,'10',float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'measurement'):
                checks.evaluate(self.step,{'volume_mm3':1000,'thickness_mm':value})

    def test_invalid_rules_rejected(self):
        variants=[]
        for field,value in [('minimum',1200),('maximum',float('inf')),('source',''),('version',''),('unit','')]:
            step=copy.deepcopy(self.step);step['checks'][0][field]=value;variants.append(step)
        step=copy.deepcopy(self.step);step['checks'][1]['id']='volume';variants.append(step)
        variants.extend([{'checks':[]},{'check':{},'checks':self.step['checks']}])
        for step in variants:
            with self.subTest(step=step),self.assertRaises(ValueError):checks.rules_for(step)

    def test_legacy_rule_remains_supported(self):
        result=checks.evaluate({'check':{'measurement':'v','minimum':2,'source':'legacy fixture'}},{'v':1})
        self.assertFalse(result[0]['passed'])

    def test_reports_preserve_failed_attempt_and_bind_output(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            state={'run_id':'fixture','revision':0,'status':'running','outputs':{'part_asset':{'file':'part.CATPart','sha256':'old'}},
                   'attempts':[{}],'events':[],'ds_status':'not_evaluated'}
            self.assertFalse(runtime.check_step(folder,state,self.step,{'volume_mm3':1000,'thickness_mm':12}))
            failed=state['check_reports']['part'].copy()
            original=(folder/failed['file']).read_bytes()
            state['outputs']['part_asset']['sha256']='new'
            self.assertTrue(runtime.check_step(folder,state,self.step,{'volume_mm3':1000,'thickness_mm':10}))
            passed=state['check_reports']['part']
            self.assertNotEqual(failed['file'],passed['file'])
            self.assertEqual((folder/failed['file']).read_bytes(),original)
            self.assertEqual(runtime.digest(folder/passed['file']),passed['sha256'])
            self.assertEqual(len(state['events']),2)
            self.assertEqual(runtime.read(folder/passed['file'])['ds_status'],'not_evaluated')


if __name__=='__main__':unittest.main()
