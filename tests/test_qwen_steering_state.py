"""开发宿主只发送已核验的保存状态，不把外部输入当作生成成果。"""
import tempfile,unittest
from pathlib import Path
from dev.qwen_steering_acceptance import model_state
from projects.steering_wheel import runtime


class ModelStateTests(unittest.TestCase):
    def test_saved_output_evidence_and_source_metadata_omission(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            for file in ['input.CATPart','output.CATPart','report.json']:(root/file).write_bytes(b'protocol fixture')
            state={'status':'completed','flow':{'steps':[{'output':'built'},{'output':'report'}]},'outputs':{
                key:{'file':file,'sha256':runtime.digest(root/file),'measurements':{},'input_manifest':{'path':'private-source'}}
                for key,file in [('source','input.CATPart'),('built','output.CATPart'),('report','report.json')]}}
            result=model_state(state,root)
            self.assertEqual(result['saved_cad_outputs'],['built'])
            self.assertNotIn('private-source',str(result))
            (root/'output.CATPart').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Persisted asset'):model_state(state,root)


if __name__=='__main__':unittest.main()
