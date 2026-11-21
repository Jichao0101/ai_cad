import unittest
from copy import deepcopy
from projects.steering_wheel.flow import ordered_steps,rebuild_plan,resolve


def step(name,inputs=(),parameters=None):
    return {'id':name,'operation':name,'inputs':{str(i):v for i,v in enumerate(inputs)},
            'parameters':parameters or {},'output':name+'_out'}


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.flow={'parameters':{'thickness':{},'offset':{}},'steps':[
            step('datum'),step('baffle',['datum_out'],{'t':{'parameter':'thickness'}}),
            step('section',['datum_out'],{'frame':[0,{'parameter':'offset'},0]}),
            step('sweep',['section_out']),step('bridge',['sweep_out','section_out']),
            step('hub',['baffle_out']),step('spoke',['baffle_out','bridge_out'])]}

    def test_rim_change_preserves_later_independent_hub(self):
        result=rebuild_plan(self.flow,['offset'],[s['id'] for s in self.flow['steps']])
        self.assertEqual(set(result['retained']),{'datum','baffle','hub'})
        self.assertEqual(set(result['execute']),{'section','sweep','bridge','spoke'})

    def test_thickness_change_preserves_rim(self):
        result=rebuild_plan(self.flow,['thickness'],[s['id'] for s in self.flow['steps']])
        self.assertEqual(set(result['retained']),{'datum','section','sweep','bridge'})
        self.assertEqual(set(result['execute']),{'baffle','hub','spoke'})

    def test_unfinished_steps_still_execute(self):
        result=rebuild_plan(self.flow,[],['datum'])
        self.assertEqual(len(result['execute']),6)

    def test_order_is_dependency_based(self):
        self.flow['steps'].reverse()
        ordered=ordered_steps(self.flow)
        self.assertEqual(ordered[0]['id'],'datum')
        self.assertEqual(ordered[-1]['id'],'spoke')

    def test_cycle_is_rejected(self):
        self.flow['steps'][0]['inputs']={'cycle':'spoke_out'}
        with self.assertRaises(ValueError): ordered_steps(self.flow)

    def test_duplicate_output_is_rejected(self):
        self.flow['steps'][1]['output']='datum_out'
        with self.assertRaises(ValueError): ordered_steps(self.flow)

    def test_unknown_binding_and_missing_object(self):
        for field,value in [('parameters',{'x':{'parameter':'unknown'}}),('inputs',{'x':'unknown'})]:
            flow=deepcopy(self.flow);flow['steps'][0][field]=value
            with self.assertRaises(ValueError): ordered_steps(flow)

    def test_inconsistent_completion_is_rejected(self):
        with self.assertRaises(ValueError): rebuild_plan(self.flow,[],['spoke'])

    def test_resolution_preserves_source_and_requires_value(self):
        source={'frame':[1,{'parameter':'offset'},3]}
        self.assertEqual(resolve(source,{'offset':4}),{'frame':[1,4,3]})
        self.assertEqual(source['frame'][1],{'parameter':'offset'})
        with self.assertRaises(ValueError): resolve(source,{})


if __name__=='__main__':unittest.main()
