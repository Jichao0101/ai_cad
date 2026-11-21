import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from projects.steering_wheel import inputs


class Collection:
    def __init__(self,names):self.items=[SimpleNamespace(Name=name) for name in names];self.Count=len(names)
    def Item(self,index):return self.items[index-1]


class InputTests(unittest.TestCase):
    def test_unique_path_does_not_select_first_duplicate(self):
        for names in ([],['same','same']):
            with self.assertRaisesRegex(ValueError,'unique'):
                inputs.resolve_object(SimpleNamespace(Bodies=Collection(names)),[{'collection':'Bodies','name':'same'}])
        found=inputs.resolve_object(SimpleNamespace(Bodies=Collection(['same'])),[{'collection':'Bodies','name':'same'}])
        self.assertEqual(found.Name,'same')

    def test_missing_unit_hash_and_path_report_before_cad(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            base={'path':str(folder/'missing.CATPart'),'sha256':'0'*64,'unit':'mm',
                  'coordinate_system':'design_global','objects':{'body':[{'collection':'Bodies','name':'Body'}]}}
            for field,value in [('unit','inch'),('coordinate_system','unknown'),('sha256','guess'),('path','relative.CATPart')]:
                with self.subTest(field=field):
                    records,issues=inputs.load(folder,{'input':{**base,field:value}})
                    self.assertFalse(records);self.assertEqual(issues[0]['category'],'input_manifest')
            records,issues=inputs.load(folder,{'input':base})
            self.assertFalse(records);self.assertIn('missing',issues[0]['message'])


if __name__=='__main__':unittest.main()
