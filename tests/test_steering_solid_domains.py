import tempfile,unittest
from pathlib import Path
from projects.steering_wheel import solid_domains


class StepDomainTests(unittest.TestCase):
    def parse(self,body):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'evidence.stp'
            path.write_text('ISO-10303-21;\nDATA;\n'+body+'\nENDSEC;\nEND-ISO-10303-21;',encoding='utf-8')
            return solid_domains.read_step(path)

    def test_strings_and_comments_do_not_create_solids(self):
        result=self.parse("#1=CLOSED_SHELL('fake #9=MANIFOLD_SOLID_BREP();',()); /* #8=MANIFOLD_SOLID_BREP(); */ #2=MANIFOLD_SOLID_BREP('name ''quoted''',#1);")
        self.assertEqual(result['step_solid_count'],1)

    def test_void_complex_entity_is_one_solid(self):
        result=self.parse("#1=CLOSED_SHELL('',()); #2=CLOSED_SHELL('',()); #3=(BREP_WITH_VOIDS((#2)) MANIFOLD_SOLID_BREP(#1));")
        self.assertEqual(result,{'step_solid_count':1,'step_closed_shell_count':2})

    def test_multiple_domains(self):
        result=self.parse("#1=CLOSED_SHELL('',()); #2=CLOSED_SHELL('',()); #3=MANIFOLD_SOLID_BREP('',#1); #4=MANIFOLD_SOLID_BREP('',#2);")
        self.assertEqual(result['step_solid_count'],2)

    def test_unsupported_and_duplicate_rejected(self):
        for body in ["#1=MAPPED_ITEM(#2,#3);", "#1=OPEN_SHELL('',());", "#1=CLOSED_SHELL('',()); #1=MANIFOLD_SOLID_BREP('',#1);",'']:
            with self.assertRaises(ValueError):self.parse(body)


if __name__=='__main__':unittest.main()
