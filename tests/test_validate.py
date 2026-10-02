import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('validator',ROOT/'scripts/validate.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.d=v.read_json(ROOT/'examples/branching.content.json')
        self.r=v.read_json(ROOT/'examples/branching.request.json')
    def check(self,code):
        result=v.validate(self.d,self.r)
        self.assertFalse(result['valid'],result)
        self.assertIn(code,{x['code'] for x in result['issues']})
        return result
    def test_complete_branching(self):
        result=v.validate(self.d,self.r)
        self.assertTrue(result['valid'],result['issues'])
        self.assertTrue(result['simulation']['complete'])
        self.assertEqual(set(result['simulation']['ending_witnesses']),{'end_depart','end_farewell'})
        final=result['simulation']['ending_witnesses']['end_depart'][-1]
        self.assertEqual(final['after'],{'trust':2,'together':True})
        self.assertFalse(result['publish_ready'])
    def test_linear(self):
        self.assertTrue(v.validate(v.read_json(ROOT/'examples/linear.content.json'),v.read_json(ROOT/'examples/linear.request.json'))['valid'])
    def test_unreachable_threshold(self):
        self.d['rule_sets']['route_depart']['rules'][0]['conditions'][0]['value']=3
        self.check('UNREACHABLE_ENDING')
    def test_choice_effect_before_route(self):
        self.d['episodes']['ep_platform']['exit']={'mode':'choice','options':[dict(key='opt_boost',label='增加信任',effects=[dict(state='trust',op='set',value=3),dict(state='together',op='set',value=True)],target=dict(type='rule_set',key='route_depart')),dict(key='opt_bye',label='道别',effects=[],target=dict(type='ending',key='end_farewell'))]}
        self.r['branch_budget']['max_choice_episodes']=2
        self.assertTrue(v.validate(self.d,self.r)['valid'])
    def test_count(self):
        self.r['length']['default_units_per_episode']=3
        self.check('COUNT')
    def test_overrides(self):
        self.r['length']['chapter_overrides']=[dict(chapter_index=2,episode_count=3)]
        self.r['length']['episode_overrides']=[dict(chapter_index=2,episode_index=3,unit_count=5)]
        rows,errs=v.expand_request(self.r)
        self.assertFalse(errs);self.assertEqual(rows[1]['unit_counts'],[2,2,5])
    def test_duplicate_override(self):
        self.r['length']['chapter_overrides']=[dict(chapter_index=1,episode_count=2)]*2
        self.check('REQUEST')
    def test_orphan(self):
        self.d['units']['orphan']=copy.deepcopy(self.d['units']['u_1_1'])
        self.d['units']['orphan']['dialogue_order']=[]
        self.check('OWNERSHIP')
    def test_missing_target(self):
        self.d['episodes']['ep_together']['exit']['target']['key']='missing'
        self.check('REFERENCE')
    def test_graph_cycle(self):
        self.d['episodes']['ep_together']['exit']['target']['key']='ep_arrival'
        self.check('CYCLE')
    def test_cross_chapter_sequence(self):
        self.d['episodes']['ep_together']['exit']={'mode':'sequence'}
        self.check('SEQUENCE')
    def test_asset_cycle(self):
        self.d['asset_specs']['lin_portrait']['references']=['lin_calm']
        self.check('ASSET_CYCLE')
    def test_no_fake_reuse(self):
        self.d['asset_specs']['station_bg']['production_mode']='reuse'
        self.check('BINDING')
    def test_spec_owner(self):
        self.d['asset_specs']['station_bg']['owner']['key']='missing'
        self.check('REFERENCE')
    def test_pose_mismatch(self):
        self.d['units']['u_1_2']['character_layers'][0]['pose']='missing'
        self.check('POSE')
    def test_unknown_field(self):
        self.d['drama']['surprise']='hidden runtime command'
        self.check('SCHEMA')
    def test_missing_capability(self):
        self.d['required_capabilities'].remove('state_rules')
        self.check('CAPABILITY')
    def test_boolean_not_integer(self):
        self.d['states']['trust']['initial']=True
        self.check('SCHEMA')
    def test_boolean_effect(self):
        self.d['episodes']['ep_arrival']['exit']['options'][0]['effects'][1]['op']='add'
        self.check('EFFECT_TYPE')
    def test_clamp(self):
        self.d['episodes']['ep_arrival']['exit']['options'][0]['effects'][0]['value']=100
        result=v.validate(self.d,self.r)
        self.assertTrue(result['valid'])
        self.assertEqual(result['simulation']['ending_witnesses']['end_depart'][-1]['after']['trust'],3)
    def test_duplicate_priority(self):
        rule=copy.deepcopy(self.d['rule_sets']['route_depart']['rules'][0]);rule['key']='rule_duplicate'
        self.d['rule_sets']['route_depart']['rules'].append(rule)
        self.check('PRIORITY')
    def test_incomplete_not_success(self):
        result=v.validate(self.d,self.r,max_states=1)
        self.assertFalse(result['valid']);self.assertFalse(result['simulation']['complete'])
        self.assertIn('SIMULATION_LIMIT',{x['code'] for x in result['issues']})
    def test_duplicate_json_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json'
            for text in ['{"a":1,"a":2}','{"a":NaN}']:
                p.write_text(text)
                with self.assertRaises(ValueError):v.read_json(p)
    def test_schema_engine_rejects_unknown_keyword(self):
        with self.assertRaises(ValueError):v.schema_errors(1,{'magic':True})
    def test_no_request_is_explicit(self):
        report=v.validate(self.d)
        self.assertIn('NO_REQUEST',{x['code'] for x in report['issues']})
    def test_voice_mismatch(self):
        self.d['dialogues']['d_1_1']['voice_asset']='station_bg'
        self.check('ASSET_TYPE')

if __name__=='__main__':unittest.main()
