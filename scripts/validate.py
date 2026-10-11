#!/usr/bin/env python3
"""Offline draft validation. No network, imports into apps, or model calls."""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8 * 1024 * 1024
SUPPORTED = {'$schema', '$defs', '$ref', 'title', 'description', 'type', 'properties',
             'required', 'additionalProperties', 'propertyNames', 'maxProperties',
             'items', 'minItems', 'maxItems', 'uniqueItems', 'enum', 'oneOf',
             'minLength', 'maxLength', 'pattern', 'minimum', 'maximum', 'exclusiveMinimum'}


def read_json(path):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError('duplicate JSON key: ' + k)
            out[k] = v
        return out
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('input exceeds 8 MiB')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('non-finite number: ' + x)))


def schema_errors(value, node, root=None, path='$'):
    """Implements only the audited keyword subset used in the bundled schemas."""
    root = node if root is None else root
    unknown = set(node) - SUPPORTED
    if unknown:
        raise ValueError('unsupported schema keywords: ' + ','.join(sorted(unknown)))
    if '$ref' in node:
        return schema_errors(value, root['$defs'][node['$ref'].split('/')[-1]], root, path)
    if 'oneOf' in node:
        matches = sum(not schema_errors(value, s, root, path) for s in node['oneOf'])
        return [] if matches == 1 else [(path, 'must match exactly one allowed shape')]
    errors = []
    def fail(msg): errors.append((path, msg))
    typ = node.get('type')
    valid_type = {'object': isinstance(value, dict), 'array': isinstance(value, list),
                  'string': isinstance(value, str), 'boolean': type(value) is bool,
                  'integer': type(value) is int, 'number': type(value) in (int, float)}
    if typ and not valid_type[typ]:
        return [(path, 'expected ' + typ)]
    if 'enum' in node and not any(type(value) is type(v) and value == v for v in node['enum']):
        fail('unsupported value')
    if isinstance(value, dict):
        for key in node.get('required', []):
            if key not in value: errors.append((path + '.' + key, 'required field missing'))
        if len(value) > node.get('maxProperties', 10000000): fail('too many entities')
        for key, v in value.items():
            p = path + '.' + key
            if 'propertyNames' in node: errors += schema_errors(key, node['propertyNames'], root, p)
            if key in node.get('properties', {}): errors += schema_errors(v, node['properties'][key], root, p)
            else:
                extra = node.get('additionalProperties', True)
                if extra is False: errors.append((p, 'unknown field'))
                elif isinstance(extra, dict): errors += schema_errors(v, extra, root, p)
    if isinstance(value, list):
        if len(value) < node.get('minItems', 0) or len(value) > node.get('maxItems', 10000000): fail('array length out of bounds')
        if node.get('uniqueItems') and len({json.dumps(x, sort_keys=True) for x in value}) != len(value): fail('duplicate array item')
        for i, v in enumerate(value): errors += schema_errors(v, node.get('items', {}), root, f'{path}[{i}]')
    if isinstance(value, str):
        if len(value) < node.get('minLength', 0) or len(value) > node.get('maxLength', 10000000): fail('text length out of bounds')
        if 'pattern' in node and not re.search(node['pattern'], value): fail('invalid format')
    if type(value) in (int, float):
        if 'minimum' in node and value < node['minimum']: fail('below minimum')
        if 'maximum' in node and value > node['maximum']: fail('above maximum')
        if 'exclusiveMinimum' in node and value <= node['exclusiveMinimum']: fail('must exceed minimum')
    return errors


def expand_request(req):
    errors = schema_errors(req, read_json(ROOT / 'schemas/request.schema.json'))
    if errors: return [], errors
    length = req['length']
    rows = [dict(chapter_index=i+1, episode_count=length['default_episodes_per_chapter'])
            for i in range(length['chapter_count'])]
    seen = set()
    for override in length['chapter_overrides']:
        c = override['chapter_index']
        if c in seen or c > len(rows): errors.append(('$.length.chapter_overrides', 'duplicate or out-of-range chapter'))
        else: rows[c-1]['episode_count'] = override['episode_count']
        seen.add(c)
    if sum(row['episode_count'] for row in rows) > 1000:
        return [], errors + [('$.length', 'authoring profile limit: 1000 episodes')]
    for row in rows: row['unit_counts'] = [length['default_units_per_episode']] * row['episode_count']
    seen = set()
    for override in length['episode_overrides']:
        c, e = override['chapter_index'], override['episode_index']
        if (c, e) in seen or c > len(rows) or e > rows[c-1]['episode_count']:
            errors.append(('$.length.episode_overrides', 'duplicate or out-of-range episode'))
        else: rows[c-1]['unit_counts'][e-1] = override['unit_count']
        seen.add((c, e))
    if sum(sum(row['unit_counts']) for row in rows) > 10000:
        errors.append(('$.length', 'authoring profile limit: 10000 units'))
    return rows, errors


def acyclic(graph):
    indegree = dict.fromkeys(graph, 0)
    for targets in graph.values():
        for t in targets: indegree[t] += 1
    ready = deque(k for k, n in indegree.items() if n == 0)
    count = 0
    while ready:
        count += 1
        for target in graph[ready.popleft()]:
            indegree[target] -= 1
            if not indegree[target]: ready.append(target)
    return count == len(graph)


def validate(content, request=None, max_states=20000):
    report = {'protocol_version': content.get('protocol_version') if isinstance(content, dict) else None,
              'valid': False, 'validation_scope': 'offline_authoring_only', 'publish_ready': False,
              'issues': [], 'counts': {}, 'simulation': {'complete': False, 'visited_states': 0, 'ending_witnesses': {}},
              'asset_usage': {}, 'limitations': ['No media existence/hash verification, no server import or publish check.',
              'Narrative coherence, identity consistency and human approval are not machine-proven.',
              'Python simulation is a draft reference; parity with Phoenix must be tested before integration.']}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    report['content_sha256'] = hashlib.sha256(canonical.encode()).hexdigest()
    def issue(code, path, message, severity='error'):
        report['issues'].append(dict(code=code, field_path=path, message=message, severity=severity))
    def has_errors(): return any(x['severity'] == 'error' for x in report['issues'])
    for path, msg in schema_errors(content, read_json(ROOT / 'schemas/content.schema.json')): issue('SCHEMA', path, msg)
    if has_errors(): return report
    d = content
    if len(d['episodes']) > 1000: issue('LIMIT', '$.episodes', 'maximum 1000 episodes')
    def check_ref(kind, key, path):
        if key not in d[kind]: issue('REFERENCE', path, 'missing ' + kind + '.' + key); return False
        return True
    # Unique ownership: dictionary entities must occur exactly once in parent ordering.
    parents = {}
    def own(orderings, children, path):
        counts = Counter()
        for parent, order in orderings:
            for key in order:
                counts[key] += 1
                parents[(children, key)] = parent
                check_ref(children, key, path + '.' + parent)
        for key in d[children]:
            if counts[key] != 1: issue('OWNERSHIP', path, key + ' must belong to exactly one parent')
    own([(d['drama']['key'], d['drama']['chapter_order'])], 'chapters', '$.drama.chapter_order')
    own([(k, v['episode_order']) for k, v in d['chapters'].items()], 'episodes', '$.chapters')
    own([(k, v['unit_order']) for k, v in d['episodes'].items()], 'units', '$.episodes')
    own([(k, v['dialogue_order']) for k, v in d['units'].items()], 'dialogues', '$.units')
    check_ref('episodes', d['drama']['start_episode'], '$.drama.start_episode')
    caps = set()
    required_assets = set()
    asset_uses = {k: [] for k in d['asset_specs']}
    def use_asset(key, usage, path, playback=False):
        if check_ref('asset_specs', key, path):
            if usage and d['asset_specs'][key]['usage'] not in usage: issue('ASSET_TYPE', path, 'incompatible asset usage')
            asset_uses[key].append(path)
            if playback: required_assets.add(key)
    def org(refs, path):
        for key in refs: use_asset(key, None, path)
    org(d['drama']['asset_refs'], '$.drama.asset_refs')
    if 'cover_asset' in d['drama']: use_asset(d['drama']['cover_asset'], {'scene','portrait','background'}, '$.drama.cover_asset', True)
    for kind in ('chapters', 'episodes'):
        for key, row in d[kind].items(): org(row['asset_refs'], f'$.{kind}.{key}.asset_refs')
    for key, char in d['characters'].items():
        use_asset(char['portrait_asset'], {'portrait'}, f'$.characters.{key}.portrait_asset')
        if 'voice_profile' in char: use_asset(char['voice_profile'], {'voice_profile'}, f'$.characters.{key}.voice_profile')
        for pose, row in char['poses'].items(): use_asset(row['asset'], {'pose'}, f'$.characters.{key}.poses.{pose}')
    for key, state in d['states'].items():
        if state['type'] == 'integer' and not state['min'] <= state['initial'] <= state['max']:
            issue('STATE_RANGE', '$.states.'+key, 'initial must be between min and max')
    def effects(rows, path):
        for i, effect in enumerate(rows):
            p = f'{path}[{i}]'
            if check_ref('states', effect['state'], p):
                typ = d['states'][effect['state']]['type']
                if typ == 'boolean' and (effect['op'] != 'set' or type(effect['value']) is not bool): issue('EFFECT_TYPE', p, 'boolean supports set boolean only')
                if typ == 'integer' and type(effect['value']) is not int: issue('EFFECT_TYPE', p, 'integer effect requires integer')
    for key, u in d['units'].items():
        p = '$.units.'+key
        caps.add(u['type'])
        use_asset(u['primary_asset'], {'scene','background'} if u['type']=='single_image' else {'background'}, p+'.primary_asset', True)
        if u['type']=='single_image' and u['character_layers']: issue('LAYER', p, 'single_image cannot have character layers')
        if len({x['slot'] for x in u['character_layers']}) != len(u['character_layers']): issue('LAYER', p, 'duplicate slot')
        for layer in u['character_layers']:
            if check_ref('characters', layer['character'], p+'.character_layers'):
                poses = d['characters'][layer['character']]['poses']
                if layer['pose'] not in poses: issue('POSE', p, 'unknown pose for this character')
                else: use_asset(poses[layer['pose']]['asset'], {'pose'}, p+'.character_layers', True)
        if u['bgm']['action']=='play':
            caps.add('bgm'); use_asset(u['bgm']['asset'], {'bgm'}, p+'.bgm', True)
        effects(u['on_enter'], p+'.on_enter')
        if u['on_enter']: caps.add('unit_effects')
    for key, row in d['dialogues'].items():
        p = '$.dialogues.'+key
        if row['speaker_type']=='character':
            if 'character' not in row: issue('SPEAKER', p, 'character reference required')
            else: check_ref('characters', row['character'], p)
        elif 'character' in row: issue('SPEAKER', p, 'non-character speaker must not carry character reference')
        if 'voice_asset' in row:
            caps.add('voice'); use_asset(row['voice_asset'], {'voice'}, p+'.voice_asset', True)
            spec = d['asset_specs'].get(row['voice_asset'], {})
            if spec and spec['specifications'].get('spoken_text') != row['text']: issue('VOICE_TEXT', p, 'voice spoken_text must exactly match dialogue')
    for key, ending in d['endings'].items():
        for field, usage in [('image_asset', {'scene','background','portrait'}), ('voice_asset', {'voice'}), ('bgm_asset', {'bgm'})]:
            if field in ending:
                use_asset(ending[field], usage, '$.endings.'+key+'.'+field, True)
                if field!='image_asset': caps.add('voice' if field=='voice_asset' else 'bgm')
    option_keys, rule_keys = set(), set()
    def target(t, path):
        return check_ref({'episode':'episodes','ending':'endings','rule_set':'rule_sets'}[t['type']], t['key'], path)
    for key, rules in d['rule_sets'].items():
        caps.add('state_rules')
        p = '$.rule_sets.'+key
        priorities = [r['priority'] for r in rules['rules']]
        if len(set(priorities))!=len(priorities): issue('PRIORITY', p, 'duplicate priority')
        target(rules['default'], p+'.default')
        for r in rules['rules']:
            if r['key'] in rule_keys: issue('KEY', p, 'duplicate rule key')
            rule_keys.add(r['key']); target(r['target'], p+'.rules.'+r['key'])
            for condition in r['conditions']:
                if check_ref('states', condition['state'], p):
                    typ = d['states'][condition['state']]['type']
                    if typ=='boolean' and (condition['op'] not in ('eq','ne') or type(condition['value']) is not bool): issue('CONDITION_TYPE', p, 'boolean condition requires eq/ne boolean')
                    if typ=='integer' and type(condition['value']) is not int: issue('CONDITION_TYPE', p, 'integer condition requires integer')
    sequences = {}
    for ch in d['chapters'].values():
        for a,b in zip(ch['episode_order'], ch['episode_order'][1:]): sequences[a] = b
    for key, ep in d['episodes'].items():
        x, p = ep['exit'], '$.episodes.'+key+'.exit'
        if x['mode']=='sequence':
            if key not in sequences: issue('SEQUENCE', p, 'sequence cannot cross chapter boundary')
        elif x['mode']=='choice':
            caps.add('episode_choices')
            for o in x['options']:
                if o['key'] in option_keys: issue('KEY', p, 'duplicate option key')
                option_keys.add(o['key']); effects(o['effects'], p+'.'+o['key']); target(o['target'], p)
                if o['effects']: caps.add('state_rules')
        else:
            if x['target']['type'] != {'episode':'episode','ending':'ending','rules':'rule_set'}[x['mode']]: issue('EXIT_MODE', p, 'mode and target type mismatch')
            target(x['target'], p)
    if d['states']: caps.add('state_rules')
    for cap in sorted(caps-set(d['required_capabilities'])): issue('CAPABILITY', '$.required_capabilities', 'missing '+cap)
    # Asset catalogue identity, production dependencies, versionless spec references.
    ag = {k: set() for k in d['asset_specs']}
    for key, spec in d['asset_specs'].items():
        p = '$.asset_specs.'+key
        expected = 'voice_profile' if spec['usage']=='voice_profile' else 'audio' if spec['usage'] in ('voice','bgm') else 'image'
        if spec['media_type'] != expected: issue('ASSET_TYPE', p, 'media_type disagrees with usage')
        owner = spec['owner']
        if owner['kind']=='drama':
            if owner['key'] != d['drama']['key']: issue('OWNER', p, 'wrong drama owner')
        else: check_ref({'chapter':'chapters','episode':'episodes','unit':'units'}[owner['kind']], owner['key'], p+'.owner')
        if spec['production_mode'] in ('create','derive') and 'prompt' not in spec: issue('PROMPT', p, 'generation prompt required')
        if spec['production_mode']=='derive' and not spec['references']: issue('REFERENCE', p, 'derive needs reference assets')
        if spec['production_mode']=='reuse' and key not in d['asset_bindings']: issue('BINDING', p, 'reuse requires supplied existing artifact binding')
        for reference in spec['references']:
            use_asset(reference, None, p+'.references')
            if reference in ag: ag[key].add(reference)
        specifications = spec['specifications']
        if spec['usage']=='voice' and 'spoken_text' not in specifications: issue('VOICE_TEXT', p, 'voice specification needs spoken_text')
        if expected=='image' and (not {'width','height'} <= set(specifications)): issue('SPECIFICATION', p, 'image needs width/height')
        if expected=='image' and set(specifications)&{'duration_seconds','loop','spoken_text','emotion','speed'}: issue('SPECIFICATION', p, 'audio fields on image')
        if expected!='image' and set(specifications)&{'width','height','transparent'}: issue('SPECIFICATION', p, 'image fields on audio/profile')
    if not acyclic(ag): issue('ASSET_CYCLE', '$.asset_specs', 'reference dependencies contain cycle')
    for key, binding in d['asset_bindings'].items():
        if check_ref('asset_specs', key, '$.asset_bindings.'+key):
            media = d['asset_specs'][key]['media_type']
            prefix = 'application/' if media=='voice_profile' else media+'/'
            if not binding['mime_type'].startswith(prefix): issue('BINDING_TYPE', '$.asset_bindings.'+key, 'MIME disagrees with spec type')
    report['asset_usage'] = asset_uses
    for key in sorted(required_assets - set(d['asset_bindings'])): issue('MISSING_MEDIA', '$.asset_specs.'+key, 'draft allowed; required playable asset has no binding', 'warning')
    for key, uses in asset_uses.items():
        if not uses: issue('UNUSED_ASSET', '$.asset_specs.'+key, 'not referenced by content or another asset', 'warning')
    report['counts'] = {k:len(d[k]) for k in ('chapters','episodes','units','dialogues','endings','asset_specs')}
    if request is not None:
        rows, errors = expand_request(request)
        for path, msg in errors: issue('REQUEST', path, msg)
        if not errors:
            chs = d['drama']['chapter_order']
            if len(chs)!=len(rows): issue('COUNT', '$.chapters', 'chapter count differs from request')
            for ch, row in zip(chs, rows):
                if ch not in d['chapters']: continue
                eps = d['chapters'][ch]['episode_order']
                if len(eps)!=row['episode_count']: issue('COUNT', '$.chapters.'+ch, 'episode count differs from request')
                for ep, n in zip(eps, row['unit_counts']):
                    if ep in d['episodes'] and len(d['episodes'][ep]['unit_order'])!=n: issue('COUNT', '$.episodes.'+ep, 'unit count differs from request')
            budget = request['branch_budget']
            if len(d['endings']) != budget['ending_count']: issue('COUNT', '$.endings', 'ending count differs from request')
            if sum(ep['exit']['mode']=='choice' for ep in d['episodes'].values()) > budget['max_choice_episodes']: issue('BUDGET', '$.episodes', 'choice episode budget exceeded')
            if len(d['states'])>budget['max_state_variables']: issue('BUDGET', '$.states', 'state variable budget exceeded')
            if sum(s['production_mode'] in ('create','derive') for s in d['asset_specs'].values()) > request['asset_budget']['max_new_specs']: issue('BUDGET', '$.asset_specs', 'new asset budget exceeded')
    else: issue('NO_REQUEST', '$', 'no request supplied; exact counts were not checked', 'warning')
    if has_errors(): return report
    # Expand rules to all potential structural edges before state simulation.
    def terminals(t):
        if t['type']!='rule_set': return [t]
        group = d['rule_sets'][t['key']]
        return [r['target'] for r in group['rules']] + [group['default']]
    graph = {k:set() for k in d['episodes']}
    for key, ep in d['episodes'].items():
        x = ep['exit']
        ts = [{'type':'episode','key':sequences[key]}] if x['mode']=='sequence' else [o['target'] for o in x['options']] if x['mode']=='choice' else [x['target']]
        graph[key] = {t['key'] for start in ts for t in terminals(start) if t['type']=='episode'}
    if not acyclic(graph):
        issue('CYCLE', '$.episodes', 'all potential episode edges must be acyclic'); return report
    def apply(state, rows):
        out = state.copy()
        for e in rows:
            definition = d['states'][e['state']]
            value = e['value'] if e['op']=='set' else out[e['state']] + e['value']
            out[e['state']] = value if definition['type']=='boolean' else max(definition['min'], min(definition['max'], value))
        return out
    fired_rules = set()
    def resolve(t, state):
        if t['type']!='rule_set': return t, None
        group = d['rule_sets'][t['key']]
        for rule in sorted(group['rules'], key=lambda x:x['priority']):
            results=[]
            for c in rule['conditions']:
                a,b=state[c['state']],c['value']
                results.append({'eq':a==b,'ne':a!=b,'gt':a>b,'gte':a>=b,'lt':a<b,'lte':a<=b}[c['op']])
            if (all(results) if rule['match']=='all' else any(results)):
                fired_rules.add(rule['key']); return rule['target'], rule['key']
        return group['default'], 'default:'+t['key']
    initial={k:s['initial'] for k,s in d['states'].items()}
    queue=deque([(d['drama']['start_episode'],initial,[])])
    visited=set(); episodes_seen=set(); witnesses={}
    while queue:
        key,before,path=queue.popleft()
        identity=(key,tuple(sorted(before.items())))
        if identity in visited: continue
        if len(visited)>=max_states:
            issue('SIMULATION_LIMIT', '$', 'state exploration incomplete; cannot certify reachability'); break
        visited.add(identity); episodes_seen.add(key)
        state=before.copy(); entry=[]
        for unit in d['episodes'][key]['unit_order']:
            prior=state.copy(); state=apply(state,d['units'][unit]['on_enter'])
            if d['units'][unit]['on_enter']: entry.append(dict(unit=unit,before=prior,after=state.copy()))
        x=d['episodes'][key]['exit']
        options=x['options'] if x['mode']=='choice' else [dict(key=None,effects=[],target={'type':'episode','key':sequences[key]} if x['mode']=='sequence' else x['target'])]
        for o in options:
            after=apply(state,o['effects']); t,rule=resolve(o['target'],after)
            step=dict(episode=key,option=o['key'],before=before,unit_effects=entry,before_choice=state,after=after,target=t,matched_rule=rule)
            trace=path+[step]
            if t['type']=='ending': witnesses.setdefault(t['key'],trace)
            else: queue.append((t['key'],after,trace))
    complete=not any(x['code']=='SIMULATION_LIMIT' for x in report['issues'])
    report['simulation']=dict(complete=complete,visited_states=len(visited),ending_witnesses=witnesses)
    if complete:
        for key in d['episodes'].keys()-episodes_seen: issue('UNREACHABLE_EPISODE', '$.episodes.'+key, 'unreachable under actual states')
        for key in d['endings'].keys()-witnesses.keys(): issue('UNREACHABLE_ENDING', '$.endings.'+key, 'no executable path to intended ending')
        for key in rule_keys-fired_rules: issue('UNREACHED_RULE', '$.rule_sets', key+' never fires (possibly shadowed)', 'warning')
    report['valid']=not has_errors()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('content', nargs='?')
    parser.add_argument('--request')
    parser.add_argument('--report')
    parser.add_argument('--max-states',type=int,default=20000)
    parser.add_argument('--plan',action='store_true',help='expand --request without content')
    args=parser.parse_args()
    try:
        if args.max_states<1: raise ValueError('--max-states must be positive')
        req=read_json(args.request) if args.request else None
        if args.plan:
            if req is None: raise ValueError('--plan requires --request')
            rows,errors=expand_request(req)
            result=dict(valid=not errors,chapters=rows,errors=errors)
        else:
            if not args.content: raise ValueError('content file required')
            result=validate(read_json(args.content),req,args.max_states)
        raw=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
        if args.report:
            dest=Path(args.report).resolve()
            if dest in {Path(p).resolve() for p in [args.content,args.request] if p}: raise ValueError('report cannot overwrite input')
            dest.write_text(raw,encoding='utf-8')
        else: print(raw,end='')
        return 0 if result['valid'] else 1
    except (ValueError,OSError,RecursionError) as e:
        print(json.dumps({'valid':False,'error':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=='__main__': sys.exit(main())
