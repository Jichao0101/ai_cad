import copy,math,unittest
from projects.steering_wheel import placement,flow


class PlacementFrameTests(unittest.TestCase):
    def test_clocking_uses_local_target_z_and_preserves_input(self):
        frame={'origin_mm':[10,20,30],'x':[0,1,0],'y':[0,0,1],'z':[1,0,0]};before=copy.deepcopy(frame)
        rotated=placement.clocked_frame(frame,90)
        self.assertLess(math.dist(rotated['x'],[0,0,1]),1e-12)
        self.assertLess(math.dist(rotated['y'],[0,-1,0]),1e-12)
        self.assertEqual(rotated['z'],frame['z']);self.assertEqual(rotated['origin_mm'],frame['origin_mm'])
        self.assertEqual(frame,before);placement.validate_frame(rotated)
        for bad in (True,float('inf'),'90'):
            with self.assertRaises(ValueError):placement.clocked_frame(frame,bad)

    def test_local_asset_requires_explicit_placement(self):
        definition={'parameters':{},'external_objects':{'local':{'coordinate_system':'part_local'}},
                    'steps':[{'id':'use','operation':'combine','inputs':{'source':'local'},'output':'out','parameters':{}}]}
        with self.assertRaisesRegex(ValueError,'must first enter place'):flow.ordered_steps(definition)
        definition['steps'][0]['operation']='place'
        self.assertEqual(flow.ordered_steps(definition)[0]['id'],'use')
        definition['steps'][0]['inputs']={'basis':'local'}
        with self.assertRaisesRegex(ValueError,'must first enter place'):flow.ordered_steps(definition)

    def test_valid_rotation_and_invalid_frames(self):
        frame={'origin_mm':[100,200,300],'x':[0,1,0],'y':[-1,0,0],'z':[0,0,1]}
        placement.validate_frame(frame)
        for changed in [{'z':[0,0,-1]},{'x':[0,2,0]},{'y':[0,1,0]},{'origin_mm':[float('nan'),0,0]}]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                placement.validate_frame({**frame,**changed})


if __name__=='__main__':unittest.main()
