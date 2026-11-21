"""模型与独立宿主读取相同参数影响关系，描述操作不访问CAD或外部资产。"""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from projects.steering_wheel import flow,runtime


class DescriptionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.definition=runtime.read(self.root/'tests/fixtures/steering_skeleton_flow.json')

    def test_transitive_branch_effects_match_executor(self):
        before=copy.deepcopy(self.definition)
        result=flow.describe(self.definition)
        effect=result['parameter_effects']['section_radius_mm']
        self.assertEqual(effect['direct_steps'],['rim'])
        self.assertEqual(effect['affected_steps'],['rim','rim_mirror','union'])
        self.assertIn('baffle',effect['unaffected_steps'])
        self.assertEqual(self.definition,before)
        result['parameters']['section_radius_mm']['max']=999
        self.assertEqual(self.definition,before)

    def test_nested_binding_paths_and_external_manifest_omission(self):
        definition=runtime.read(self.root/'tests/fixtures/steering_baffle_flow.json')
        definition['external_objects']={'cas':{'path':'NOT_FOR_MODEL.CATPart','sha256':'private_input_hash'}}
        definition['steps'][1]['parameters']['nested']={'a/b~c':[{'parameter':'thickness_mm'}]}
        result=flow.describe(definition)
        paths=result['steps'][1]['parameter_bindings']['thickness_mm']
        self.assertIn('/thickness_mm',paths)
        self.assertIn('/nested/a~1b~0c/0',paths)
        self.assertNotIn('NOT_FOR_MODEL',json.dumps(result))
        self.assertNotIn('private_input_hash',json.dumps(result))
        self.assertNotIn('outline',result['steps'][1])

    def test_describe_cli_needs_no_run_or_existing_external_asset(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            definition=copy.deepcopy(self.definition)
            definition['external_objects']={'cas':{'path':'missing.CATPart'}}
            (root/'flow.json').write_text(json.dumps(definition),encoding='utf-8')
            (root/'request.json').write_text(json.dumps({'flow':str(root/'flow.json')}),encoding='utf-8')
            result=subprocess.run([sys.executable,'-X','utf8',str(self.root/'tools/steering_cli.py'),'describe',str(root/'request.json')],capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),flow.describe(definition))
            self.assertEqual({p.name for p in root.iterdir()},{'request.json','flow.json'})


if __name__=='__main__':unittest.main()
