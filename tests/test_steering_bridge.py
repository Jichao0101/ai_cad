import copy,unittest
from projects.steering_wheel import rim_bridge


class BridgeInputTests(unittest.TestCase):
    def setUp(self):
        self.parameters={'section_kind':'rectangle','sections':[
            {'center_mm':[0,0,z],'x':[1,0,0],'y':[0,1,0],'width_mm':20,'thickness_mm':5} for z in [0,40]]}

    def test_ambiguous_orientation_rejected_before_cad(self):
        for y in ([0,-1,0],[0,0,1]):
            p=copy.deepcopy(self.parameters);p['sections'][1]['y']=y
            with self.assertRaisesRegex(ValueError,'travel direction'):rim_bridge.create(None,None,p)

    def test_degenerate_pair_rejected_before_cad(self):
        self.parameters['sections'][1]['center_mm']=[0,0,0]
        with self.assertRaisesRegex(ValueError,'distinct'):rim_bridge.create(None,None,self.parameters)

    def test_invalid_dimension_rejected_before_cad(self):
        for value in (False,0,-1,float('nan')):
            self.parameters['sections'][1]['thickness_mm']=value
            with self.assertRaisesRegex(ValueError,'dimensions'):rim_bridge.create(None,None,self.parameters)

    def test_endpoint_coordinates_use_basis_and_reject_missing_evidence(self):
        basis={'origin_mm':[10,20,30],'x':[0,1,0],'y':[-1,0,0],'z':[0,0,1]}
        spec={'center_mm':[10,25,40],'x':[0,1,0],'y':[-1,0,0],'radius_mm':2}
        record={'measurements':{'end_sections':{'coordinate_system':'design_global','section_kind':'circle',
                    'sections':{'start':spec,'end':spec}}}}
        records={'first':record,'second':record};ends={'first':'end','second':'start'}
        result=rim_bridge.from_endpoints(basis,records,ends)
        self.assertEqual(result['sections'][0],{'center_mm':[5,0,10],'x':[1,0,0],'y':[0,1,0],'radius_mm':2})
        with self.assertRaisesRegex(ValueError,'no supported'):
            rim_bridge.from_endpoints(basis,{'first':{'measurements':{}},'second':record},ends)


if __name__=='__main__':unittest.main()
