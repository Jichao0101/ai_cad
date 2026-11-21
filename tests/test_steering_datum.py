import unittest
from projects.steering_wheel import datum,baffle


class DatumTest(unittest.TestCase):
    def setUp(self):
        self.inputs={'column_point':[0,0,0],'column_direction':[0,0,1],
                     'symmetry_point':[0,0,0],'symmetry_normal':[0,1,0],
                     'outer_3':[20,100,40],'outer_9':[40,-100,40],
                     'bottom_point':[0,0,10],'bottom_normal':[0,0,1],
                     'origin_rule':'sor_3_9','y_negative_extremum':[50,-100,40]}

    def test_sor_projection(self):
        frame=datum.solve(self.inputs)
        self.assertEqual(frame['origin_mm'],[30,0,10])
        self.assertEqual(frame['sketch_frame'],[30,0,10,1,0,0,0,1,0])

    def test_alternative_is_not_silently_equated(self):
        self.inputs['origin_rule']='flow_y_extremum'
        self.assertEqual(datum.solve(self.inputs)['origin_mm'],[50,-100,10])

    def test_parallel_projection_is_rejected(self):
        self.inputs['bottom_normal']=[1,0,0]
        with self.assertRaises(ValueError): datum.solve(self.inputs)

    def test_axis_not_in_plane_is_rejected(self):
        self.inputs['column_point']=[0,1,0]
        with self.assertRaises(ValueError): datum.solve(self.inputs)

    def test_no_implicit_origin_rule(self):
        self.inputs['origin_rule']='default'
        with self.assertRaises(ValueError): datum.solve(self.inputs)

    def test_native_projection_must_stay_on_declared_axis_line(self):
        frame=datum.solve(self.inputs,[30,0,15])
        self.assertEqual(frame['origin_mm'],[30,0,15])
        with self.assertRaises(ValueError):datum.solve(self.inputs,[31,0,15])

    def test_baffle_rejects_crossed_and_concave_profiles(self):
        frame=datum.solve(self.inputs)['sketch_frame']
        for points in [[[0,0],[2,2],[0,2],[2,0]],[[0,0],[2,0],[1,.5],[2,2],[0,2]]]:
            with self.assertRaises(ValueError): baffle.validate_profile(points,frame,8.4)

    def test_round_baffle_rejects_invalid_radius_and_ambiguous_profile(self):
        frame=datum.solve(self.inputs)['sketch_frame']
        for radius in [0,-1,True,float('nan')]:
            with self.assertRaises(ValueError):baffle.create(None,None,frame,8.4,radius)
        with self.assertRaises(ValueError):baffle.create(None,[[0,0],[1,0],[0,1]],frame,8.4,10)


if __name__=='__main__': unittest.main()
