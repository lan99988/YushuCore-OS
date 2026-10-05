"""Authorized automation over existing CoreRuntime, with metadata-only state."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from threading import Event, Thread
import time
import uuid

import yaml

from . import __version__
from yushuos_sdk.canonical import digest, loads, request_id, run_id as stable_run_id
from yushuos_sdk.metadata import safe_resource_refs
from .automation_store import AutomationStore
from .registry import provider_digest
from .models import Result
from .runtime import CoreRuntime, PluginRunner
from .scheduler import next_due, occurrence_key, stamp, utc


_IDENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')


def _ordinary(path):
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda:False)() for p in (path, *path.parents)):
        raise ValueError('Linked automation paths are not permitted')
    return path


class AutomationEngine:
    def __init__(self, runtime, *, clock=None):
        self.runtime = runtime
        self.root = Path(runtime.config['_config_root'])
        self.project_file = runtime.config.get('_project_file') or None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = AutomationStore(_ordinary(self.root / 'state' / 'automation.sqlite'))

    def now(self):
        return stamp(self.clock())

    def fresh(self):
        runner = self.runtime.runner
        return CoreRuntime(self.root, project_file=self.project_file,
                           runner=None if isinstance(runner, PluginRunner) else runner)

    def settings(self):
        path = _ordinary(self.root / 'automation.yaml')
        config = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(config, dict) or set(config) - {'schema_version','timezone','history_retention_days'}:
            raise ValueError('Invalid automation settings')
        if type(config.get('schema_version',1)) is not int or config.get('schema_version', 1) != 1:
            raise ValueError('Unsupported automation settings version')
        from zoneinfo import ZoneInfo
        ZoneInfo(config.get('timezone','Asia/Shanghai'))
        retention = config.get('history_retention_days',90)
        if type(retention) is not int or not 1 <= retention <= 36500:
            raise ValueError('Invalid history retention')
        return {'timezone':config.get('timezone','Asia/Shanghai'),'history_retention_days':retention}

    def _template(self, rule, runtime):
        action = rule['action']
        owner = runtime.registry.plugins.get(action['plugin_id'])
        if owner is None:
            raise ValueError('Action provider is unavailable')
        ref = action['action_ref']
        if not isinstance(ref, str) or not _IDENT.fullmatch(ref):
            raise ValueError('Invalid action reference')
        directory = PluginRunner(runtime.config)._data_path(owner, create=False) / 'actions'
        path = _ordinary(directory / (ref + '.json'))
        if not path.is_file() or path.stat().st_size > 131072:
            raise ValueError('Action template is missing or too large')
        raw = loads(path.read_bytes())
        if not isinstance(raw, dict):
            raise ValueError('Invalid action template')
        project = runtime.config.get('project_ref','')
        if raw.get('project_ref',project) != project:
            raise ValueError('Action project mismatch')
        if 'steps' in raw:
            if set(raw) - {'project_ref','steps'} or not isinstance(raw['steps'],list) or not raw['steps']:
                raise ValueError('Invalid workflow template')
            entries = raw['steps']
        else:
            if set(raw) - {'project_ref','capability','intent','fields','target'}:
                raise ValueError('Invalid action template fields')
            entries = [{'step_id':'main', **{k:v for k,v in raw.items() if k!='project_ref'}}]
        steps = []
        for entry in entries:
            if not isinstance(entry,dict) or set(entry) - {'step_id','capability','intent','fields','target','depends_on'}:
                raise ValueError('Invalid action step')
            steps.append({'step_id':entry.get('step_id'), 'capability':entry.get('capability'),
                          'intent':entry.get('intent'),'fields':entry.get('fields',{}),
                          'target':entry.get('target',{}),'depends_on':entry.get('depends_on',[])})
        template = {'project_ref':project,'steps':steps}
        runtime.build_plan(self._requests(template,stable_run_id('validation',1,'validation')))
        return template, owner

    @staticmethod
    def _requests(template, run):
        return {'project_ref':template['project_ref'], 'steps':[
            {**entry, 'request_id':request_id(run,entry['step_id'])} for entry in template['steps']]}

    def _describe(self, rule, runtime=None):
        runtime = runtime or self.fresh()
        template, owner = self._template(rule,runtime)
        pins = []
        dependencies = {}
        def visit(spec):
            if spec.plugin_id in dependencies:
                return
            dependencies[spec.plugin_id] = {'plugin_id':spec.plugin_id,'version':spec.version,
                                            'provider_digest':provider_digest(spec,runtime.config)}
            for dependency in spec.dependencies:
                if dependency in runtime.registry.plugins:
                    visit(runtime.registry.plugins[dependency])
        visit(owner)
        for entry in template['steps']:
            binding = runtime._binding(entry['capability'])
            if binding is None:
                raise ValueError('Action capability is unavailable')
            visit(binding.plugin)
            for dep in binding.capability.dependencies:
                if dep in runtime.registry.plugins:
                    visit(runtime.registry.plugins[dep])
            req = runtime._request({'request_id':request_id(stable_run_id('validation',1,'validation'),entry['step_id']),
                                    **{k:entry[k] for k in ('capability','intent','fields','target')},
                                    'project_ref':template['project_ref']})
            gate = runtime._gate(binding,req,mode='execute',host_mode='execute')
            if gate is not None:
                raise ValueError('Action cannot pass runtime gates')
            cap = binding.capability
            scopes = dict(cap.resource_scopes)
            resources = runtime.config.get('bindings',{}).get('resources',{})
            pins.append({'step_id':entry['step_id'],'plugin_id':binding.plugin.plugin_id,
                         'version':binding.plugin.version,'provider_digest':provider_digest(binding.plugin,runtime.config),
                         'capability':cap.name,'intent':entry['intent'],'effect':cap.effect,
                         'execution_mode':cap.execution_mode,'permissions':sorted(set(cap.permissions)|set(binding.plugin.permissions)),
                         'resource_hash':digest({key:resources.get(scope) for key,scope in scopes.items()}),
                         'target_hash':digest(entry['target'])})
        return template, digest(template), {'steps':pins,'providers':sorted(dependencies.values(),key=lambda p:p['plugin_id'])}

    def add(self, value):
        allowed = {'schema_version','id','project_ref','enabled','trigger','action','misfire_policy','grace_seconds','misfire_window_seconds'}
        if (not isinstance(value,dict) or set(value)-allowed or type(value.get('schema_version',1)) is not int
                or value.get('schema_version',1)!=1):
            raise ValueError('Invalid rule definition')
        if not isinstance(value.get('id'),str) or not _IDENT.fullmatch(value['id']):
            raise ValueError('Invalid rule ID')
        runtime = self.fresh()
        project = runtime.config.get('project_ref','')
        if value.get('project_ref',project)!=project:
            raise ValueError('Rule project mismatch')
        action = value.get('action')
        if not isinstance(action,dict) or set(action)!={'plugin_id','action_ref'}:
            raise ValueError('Action must reference a plugin-private template')
        trigger = dict(value.get('trigger',{}))
        kind = trigger.get('type')
        fields = {'manual':{'type'},'event':{'type','event_type','source'},'cron':{'type','expression','timezone'},
                  'interval':{'type','seconds','anchor'}}
        if kind not in fields or set(trigger)-fields[kind]:
            raise ValueError('Invalid trigger definition')
        if kind=='cron':
            trigger.setdefault('timezone',self.settings()['timezone'])
        if kind=='interval':
            trigger.setdefault('anchor',self.now())
            trigger['anchor'] = stamp(trigger['anchor'])
        if kind=='event' and (not isinstance(trigger.get('event_type'),str) or not isinstance(trigger.get('source'),str)):
            raise ValueError('Event triggers require an exact source and type')
        enabled = value.get('enabled',False)
        if type(enabled) is not bool:
            raise ValueError('Rule enabled must be boolean')
        policy = value.get('misfire_policy','skip')
        if policy not in {'skip','latest'}:
            raise ValueError('Invalid misfire policy')
        grace, window = value.get('grace_seconds',60), value.get('misfire_window_seconds',3600)
        if any(type(n) is not int or not 1<=n<=86400 for n in (grace,window)):
            raise ValueError('Invalid misfire window')
        rule = {'id':value['id'],'project_ref':project,'trigger':trigger,'action':dict(action),
                'misfire_policy':policy,'grace_seconds':grace,'misfire_window_seconds':window}
        _, action_hash, pins = self._describe(rule,runtime)
        rule.update({'action_hash':action_hash,'pins':pins})
        rule['revision'] = digest({'kind':'rule-v1',**rule})
        rule['enabled'] = enabled
        rule['next_due'] = next_due(trigger,self.now())
        existing = self.store.get_rule(rule['id'])
        if existing and existing['revision']==rule['revision']:
            rule['next_due'] = existing.get('next_due')
        self.store.put_rule(rule)
        return self.store.get_rule(rule['id'])

    def _rule(self, rule_id):
        rule = self.store.get_rule(rule_id)
        if rule is None or rule.get('project_ref','') != self.runtime.config.get('project_ref',''):
            raise ValueError('Rule is unavailable in this project')
        return rule

    def preview(self, rule_id):
        rule = self._rule(rule_id)
        try:
            _, action_hash, pins = self._describe(rule)
            ready = action_hash==rule['action_hash'] and pins==rule['pins']
        except (ValueError,OSError):
            action_hash, pins, ready = rule['action_hash'], rule['pins'], False
        return {'status':'preview' if ready else 'blocked','rule_id':rule_id,'revision':rule['revision'],
                'action_hash':action_hash,'pins':pins,'host_required':any(p['execution_mode']=='host_required' for p in pins['steps']),
                'write_performed':False}

    def grant(self, rule_id):
        rule = self._rule(rule_id)
        if self.preview(rule_id)['status']!='preview':
            raise ValueError('Rule definition changed; register a new revision first')
        grant = {'grant_id':'grant-'+uuid.uuid4().hex,'rule_id':rule_id,'revision':rule['revision'],
                 'action_hash':rule['action_hash'],'pins':rule['pins'],'created_at':self.now(),
                 'expires_at':stamp(utc(self.now())+timedelta(days=30)),'canonicalization':'jcs-v1'}
        self.store.save_grant(rule_id,grant)
        return grant

    def _authorized(self, rule):
        current = self._rule(rule['id'])
        if current['revision']!=rule['revision']:
            return False
        grant = self.store.active_grant(rule['id'],self.now())
        if grant is None or any(grant.get(k)!=rule.get(k) for k in ('revision','action_hash','pins')):
            return False
        return self.preview(rule['id'])['status']=='preview'

    def _timely(self,rule,run):
        if not run['occurrence_key'].startswith(('cron:','interval:')):
            return True
        age=(utc(self.now())-utc(run['scheduled_at'])).total_seconds()
        if age<=rule['grace_seconds']:
            return True
        return (rule['misfire_policy']=='latest' and age<=rule['misfire_window_seconds']
                and utc(next_due(rule['trigger'],run['scheduled_at']))>utc(self.now()))

    def run(self, rule_id, *, invocation_id=None, host=False, run_id=None):
        rule = self._rule(rule_id)
        if run_id:
            run = self.store.show_run(run_id)
            if run is None or run['rule_id']!=rule_id:
                raise ValueError('Run is unavailable')
            if run['status']=='unknown' and host and run.get('resolution'):
                if self.store.release_resolved_run(run_id):
                    return self._execute(self.store.show_run(run_id),host=True)
            if run['status']!='host_pending':
                return run
            if not host:
                return run
            self.store.release_host_pending(run_id)
            return self._execute(self.store.show_run(run_id),host=True)
        invocation_id = invocation_id or uuid.uuid4().hex
        if not isinstance(invocation_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',invocation_id):
            raise ValueError('Invalid invocation ID')
        run = self.store.enqueue_run(rule, 'manual:'+invocation_id, self.now())
        return self._execute(run,host=host)

    def _execute(self, run, *, host=False):
        if run['status'] not in {'pending','running'}:
            return run
        owner = uuid.uuid4().hex
        lease = self.store.claim_run(run['run_id'],owner,self.now())
        if lease is None:
            return self.store.show_run(run['run_id'])
        generation = lease['lease_generation']
        stopped = Event()
        lost = Event()
        def heartbeat():
            while not stopped.wait(5):
                try:
                    if not self.store.renew_lease(run['run_id'],owner,generation,self.now()):
                        lost.set(); return
                except Exception:
                    lost.set(); return
        thread = Thread(target=heartbeat,daemon=True)
        thread.start()
        try:
            active_path=self.root/'active.json'
            active_pointer=active_path.read_bytes() if active_path.exists() else None
            rule = self._rule(run['rule_id'])
            if rule['revision']==run['revision'] and not self._timely(rule,run):
                return self._finish(run,owner,generation,'misfire_skipped','misfire')
            manual=run['occurrence_key'].startswith('manual:')
            if rule['revision']!=run['revision'] or (not manual and not rule['enabled']) or not self._authorized(rule):
                return self._finish(run,owner,generation,'blocked','authorization_required')
            self.store.set_run_authorization(run['run_id'],self.store.active_grant(rule['id'],self.now()),
                owner=owner,generation=generation,now=self.now())
            runtime = self.fresh()
            template, _, pins = self._describe(rule,runtime)
            if not host and any(p['execution_mode']=='host_required' for p in pins['steps']):
                return self._finish(run,owner,generation,'host_pending')
            delegate = runtime.runner
            engine = self
            def check_authority():
                current_pointer=active_path.read_bytes() if active_path.exists() else None
                if (current_pointer!=active_pointer or lost.is_set() or not engine._authorized(rule)
                        or (not manual and not engine._rule(rule['id'])['enabled'])):
                    raise ValueError('Execution authority changed')
                try:
                    engine.store.renew_lease(run['run_id'],owner,generation,engine.now())
                except ValueError:
                    lost.set()
                    raise
            runtime.config['_execution_guard']=check_authority
            class GuardedRunner:
                def invoke(self, binding, request, **kwargs):
                    check_authority()
                    return delegate.invoke(binding,request,**kwargs)
            runtime.runner = GuardedRunner()
            runtime.config['_execution_context'] = {'run_id':run['run_id'],
                'root_event_id':run.get('root_event_id') or '', 'causation_id':run.get('event_id') or '',
                'depth':run.get('depth',0),'execution_origin':'host' if host else 'automation'}
            self.store.mark_dispatched(run['run_id'],owner,generation,self.now())
            value = self._requests(template,run['run_id'])
            if len(value['steps'])==1 and value['steps'][0]['step_id']=='main':
                entry = value['steps'][0]
                result = runtime.invoke({k:v for k,v in entry.items() if k not in {'step_id','depends_on'} }|
                                        {'project_ref':template['project_ref']},mode='execute',host_mode='execute').to_dict()
            else:
                result = runtime.execute_plan(value,host_mode='execute')
            status = result['status']
            for pin in pins['steps']:
                if status=='succeeded' and pin['effect'] in {'internal_write','external_write'}:
                    receipt = runtime.state.receipt(request_id(run['run_id'],pin['step_id'])) if runtime.state else None
                    if not receipt or receipt['status']!='succeeded':
                        status='unknown'
            if status not in {'succeeded','failed','unknown','partial','verification_pending'}:
                status='blocked'
            return self._finish(run,owner,generation,status,'' if status=='succeeded' else 'execution_'+status,
                                safe_resource_refs(result.get('resource',{})))
        except Exception:
            state = self.store.show_run(run['run_id'])
            status = 'unknown' if state and state.get('dispatched') else 'blocked'
            try:
                return self._finish(run,owner,generation,status,'execution_interrupted')
            except ValueError:
                return self.store.show_run(run['run_id'])
        finally:
            stopped.set()
            thread.join(timeout=1)

    def _finish(self, run, owner, generation, status, error_code='',resource_refs=None):
        self.store.update_run(run['run_id'],owner,generation,status,self.now(),
                              error_code=error_code,resource_refs=resource_refs or {})
        return self.store.show_run(run['run_id'])

    def publish(self, value):
        if not isinstance(value,dict) or set(value)-{'type','resource_refs','id'} or not isinstance(value.get('type'),str):
            raise ValueError('CLI events cannot specify a plugin source')
        event_id = value.get('id') or 'event-'+uuid.uuid4().hex
        event = {'id':event_id,'type':value['type'],'source_plugin':'core.cli','source_version':__version__,
                 'project_ref':self.runtime.config.get('project_ref',''),'request_id':'',
                 'causation_id':'','root_event_id':event_id,'occurred_at':self.now(),'depth':0,
                 'resource_refs':safe_resource_refs(value.get('resource_refs',{}))}
        self.store.publish_event(event)
        return event

    def resolve(self, operation_id, outcome, *, reason_code, evidence_ref=''):
        runtime=self.fresh()
        if not runtime.state:
            raise ValueError('未绑定原操作台账，无法核验请求')
        associated=[]
        # Include old revisions through frozen snapshots, rather than rebuilding
        # the historical identity from the current plugin/template definition.
        for entry in self.store.find_runs_for_request(operation_id,runtime.config.get('project_ref','')):
            run=entry['run']
            snapshot=run.get('rule_snapshot') or {}
            steps=snapshot.get('pins',{}).get('steps',[])
            if any(request_id(run['run_id'],p['step_id'])==operation_id for p in steps):
                associated.append((run,steps))
        value=runtime.state.resolve(operation_id,outcome,actor='core.cli',reason_code=reason_code,evidence_ref=evidence_ref)
        for run,steps in associated:
            outcomes=[]
            unresolved=False
            for step in steps:
                receipt=runtime.state.effective_receipt(request_id(run['run_id'],step['step_id']))
                if receipt:
                    status=receipt['status']
                    if status in {'unknown','dispatched','verifying','verification_pending','partial'}:
                        unresolved=True
                    if receipt.get('resolution'):
                        outcomes.append(receipt['resolution']['outcome'])
            if not unresolved and outcomes:
                status='abandoned' if 'abandoned' in outcomes else 'verified_failed' if 'verified_failed' in outcomes else 'verified_success'
                self.store.resolve_run(run['run_id'],status,actor='core.cli',reason_code=reason_code,evidence_ref=evidence_ref)
        return value

    def import_outbox(self):
        runtime = self.fresh()
        if not runtime.state:
            return 0
        count=0
        for entry in runtime.state.pending_outbox():
            event = entry.get('envelope',entry.get('event',entry))
            spec = runtime.registry.plugins.get(event['source_plugin'])
            if spec is None or event['type'] not in spec.emitted_events or event['source_version']!=spec.version:
                continue
            if event.get('provider_digest')!=provider_digest(spec,runtime.config):
                continue
            self.store.publish_event(event)
            runtime.state.mark_outbox_imported(event['id'])
            count+=1
        return count

    def tick(self, *, execute=True):
        imported = self.import_outbox()
        registered=[]
        # Expire crash-left queued time occurrences before evaluating a fresh
        # due occurrence, so an expired pending row cannot starve the latest one.
        for pending in self.store.list_runs(status='pending',limit=1000):
            snapshot=pending.get('rule_snapshot') or {}
            if snapshot.get('project_ref','')!=self.runtime.config.get('project_ref',''):
                continue
            rule=self._rule(pending['rule_id'])
            if rule['revision']==pending['revision'] and not self._timely(rule,pending):
                owner=uuid.uuid4().hex
                lease=self.store.claim_run(pending['run_id'],owner,self.now())
                if lease:
                    registered.append(self._finish(pending,owner,lease['lease_generation'],'misfire_skipped','misfire'))
        rules=[r for r in self.store.list_rules() if r.get('enabled') and r.get('project_ref','')==self.runtime.config.get('project_ref','')]
        for event in self.store.pending_events():
            if event.get('project_ref','')!=self.runtime.config.get('project_ref',''):
                continue
            for rule in rules:
                trigger=rule['trigger']
                if trigger['type']=='event' and trigger['source']==event['source_plugin'] and trigger['event_type']==event['type']:
                    registered.append(self.store.enqueue_run(rule,'event:'+event['id'],event['occurred_at'],
                        root_event_id=event['root_event_id'],depth=event['depth']))
            self.store.mark_event_delivered(event['id'])
        for rule in rules:
            due=rule.get('next_due')
            if rule['trigger']['type'] not in {'cron','interval'} or not due:
                continue
            for _ in range(1024):
                if utc(due)>utc(self.now()):
                    break
                following=next_due(rule['trigger'],due)
                age=(utc(self.now())-utc(due)).total_seconds()
                latest=utc(following)>utc(self.now())
                runnable=age<=rule['grace_seconds'] or (rule['misfire_policy']=='latest' and latest and age<=rule['misfire_window_seconds'])
                run=self.store.enqueue_run(rule,occurrence_key(rule['trigger'],due),due)
                if not runnable and run['status']=='pending':
                    owner=uuid.uuid4().hex
                    lease=self.store.claim_run(run['run_id'],owner,self.now())
                    if lease:
                        run=self._finish(run,owner,lease['lease_generation'],'misfire_skipped','misfire')
                registered.append(run)
                if not self.store.update_cursor(rule['id'],rule['revision'],following):
                    break
                due=following
        if execute:
            pending=self.store.list_runs(status='pending',limit=1000)+self.store.list_runs(status='running',limit=1000)
            seen={r['run_id'] for r in registered}
            registered.extend(r for r in pending if r['run_id'] not in seen
                and (r.get('rule_snapshot') or {}).get('project_ref','')==self.runtime.config.get('project_ref',''))
        results=[self._execute(run) for run in registered] if execute else registered
        cutoff=stamp(utc(self.now())-timedelta(days=self.settings()['history_retention_days']))
        self.store.purge_history(cutoff)
        return {'status':'succeeded','imported_events':imported,'runs':results}

    def worker(self, *, max_ticks=None):
        futures={}
        ticks=0
        active_path=self.root/'active.json'
        active_digest=active_path.read_bytes() if active_path.exists() else None
        with ThreadPoolExecutor(max_workers=4) as pool:
            try:
                while max_ticks is None or ticks<max_ticks:
                    if (active_path.read_bytes() if active_path.exists() else None)!=active_digest:
                        break
                    self.tick(execute=False)
                    for key in list(futures):
                        if futures[key].done():
                            futures.pop(key).result()
                    candidates=self.store.list_runs(status='pending',limit=1000)+self.store.list_runs(status='running',limit=1000)
                    for run in candidates:
                        if len(futures)>=4:
                            break
                        if run['run_id'] not in futures and self.store.get_rule(run['rule_id']).get('project_ref','')==self.runtime.config.get('project_ref',''):
                            futures[run['run_id']]=pool.submit(self._execute,run)
                    ticks+=1
                    if max_ticks is None or ticks<max_ticks:
                        time.sleep(1)
            except KeyboardInterrupt:
                pass
        for future in futures.values():
            future.result()
        return {'status':'stopped','ticks':ticks}
