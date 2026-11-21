"""移交只复制已核验资产，不改写状态，也不授予正式发布。"""
import json,tempfile,unittest
from pathlib import Path
from projects.steering_wheel import runtime,handover


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        definition=runtime.read(Path(__file__).parent/'fixtures/steering_baffle_flow.json')
        definition['steps']=definition['steps'][:1]
        self.folder,self.state=runtime.start(definition,{},self.root)
        # 文件复制协议测试，不冒充CATIA有效文件；真实模型另行实测。
        model=self.folder/'synthetic.CATPart';model.write_bytes(b'copy protocol fixture only')
        self.state['outputs']['model']={'file':model.name,'sha256':runtime.digest(model),'measurements':{}}
        (self.folder/'state.json').write_text(json.dumps(self.state),encoding='utf-8')
        self.target=self.root/'handover'

    def test_export_preserves_hashes_and_state_and_marks_development(self):
        before=(self.folder/'state.json').read_bytes()
        result=handover.export(self.folder,self.state['revision'],'model',self.target)
        manifest=runtime.read(result['manifest'])
        self.assertEqual(manifest['release_status'],'development_only')
        self.assertEqual(manifest['ds_status'],'not_evaluated')
        self.assertTrue(manifest['fixture_only'])
        self.assertEqual(len(manifest['basis_files']),1)
        self.assertTrue(all(runtime.digest(self.target/name)==value for name,value in manifest['files'].items()))
        self.assertEqual((self.folder/'state.json').read_bytes(),before)
        with self.assertRaises(FileExistsError):handover.export(self.folder,self.state['revision'],'model',self.target)

    def test_changed_asset_and_stale_revision_rejected_before_directory_creation(self):
        with self.assertRaisesRegex(ValueError,'revision'):
            handover.export(self.folder,self.state['revision']-1,'model',self.target)
        (self.folder/'synthetic.CATPart').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'asset changed'):
            handover.export(self.folder,self.state['revision'],'model',self.target)
        self.assertFalse(self.target.exists())

    def test_unfinished_or_overlapping_destination_rejected(self):
        with self.assertRaisesRegex(ValueError,'separate'):
            handover.export(self.folder,self.state['revision'],'model',self.folder/'export')
        self.state['status']='check_failed'
        (self.folder/'state.json').write_text(json.dumps(self.state),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'completed'):
            handover.export(self.folder,self.state['revision'],'model',self.target)
        self.assertFalse(self.target.exists())


if __name__=='__main__':unittest.main()
