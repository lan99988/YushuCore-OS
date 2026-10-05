import importlib
import json
from pathlib import Path

import pytest
import yaml

from test_yushuos_core import make_plugin, write_config
from yushuos.deployment import lock_plugin
from yushuos.runtime import CoreRuntime
from yushuos_sdk import Result


class Runner:
    def __init__(self):
        self.calls = []

    def invoke(self, binding, request, **kwargs):
        self.calls.append(request.request_id)
        return Result('succeeded', request.request_id, data={'received': request.fields['message']})


def setup(tmp_path, *, host=False):
    root = tmp_path / 'core'
    plugin = make_plugin(root)
    manifest = yaml.safe_load((plugin / 'plugin.yaml').read_text(encoding='utf-8'))
    manifest['contract_version'] = 3
    manifest['runner']['protocol'] = 'json-stdio-v2'
    manifest['capabilities'][0]['execution_mode'] = 'host_required' if host else 'standalone'
    (plugin / 'plugin.yaml').write_text(yaml.safe_dump(manifest),encoding='utf-8')
    lock_plugin(plugin)
    runner = Runner()
    runtime = CoreRuntime(root, runner=runner)
    data = runtime.runner._data_path if hasattr(runtime.runner, '_data_path') else None
    action_dir = root / 'plugin-data' / manifest['id'] / manifest['data_path'] / 'actions'
    action_dir.mkdir(parents=True)
    action = {'capability':'example.echo','intent':'read','fields':{'message':'private business text'}}
    (action_dir / 'hello.json').write_text(json.dumps(action),encoding='utf-8')
    try:
        module = importlib.import_module('yushuos.automation')
    except ModuleNotFoundError:
        module = None
    assert module is not None, 'Automation engine must exist'
    engine = module.AutomationEngine(runtime, clock=lambda:'2026-10-05T00:00:00.000000Z')
    rule = {'schema_version':1,'id':'demo-rule','trigger':{'type':'manual'},'action':{'plugin_id':manifest['id'],'action_ref':'hello'}}
    return engine, rule, runner, plugin, action_dir


def test_manual_grant_and_duplicate_invocation_execute_once(tmp_path):
    engine, rule, runner, *_ = setup(tmp_path)
    engine.add(rule)
    assert engine.run('demo-rule', invocation_id='not-granted')['status'] == 'blocked'
    engine.grant('demo-rule')
    first = engine.run('demo-rule', invocation_id='same')
    second = engine.run('demo-rule', invocation_id='same')
    assert first['status'] == second['status'] == 'succeeded'
    assert len(runner.calls) == 1
    assert first['run_id'] == second['run_id']


def test_metadata_store_excludes_action_body(tmp_path):
    engine, rule, *_ = setup(tmp_path)
    engine.add(rule)
    engine.grant('demo-rule')
    engine.run('demo-rule', invocation_id='privacy')
    db = Path(engine.store.path)
    assert b'private business text' not in db.read_bytes()


def test_host_required_does_not_start_plugin(tmp_path):
    engine, rule, runner, *_ = setup(tmp_path, host=True)
    engine.add(rule)
    engine.grant('demo-rule')
    result = engine.run('demo-rule', invocation_id='host')
    assert result['status'] == 'host_pending'
    assert runner.calls == []


def test_same_version_changed_package_revokes_authorization(tmp_path):
    engine, rule, runner, plugin, *_ = setup(tmp_path)
    engine.add(rule)
    engine.grant('demo-rule')
    with (plugin / 'run.py').open('a',encoding='utf-8') as f:
        f.write('\n# local change\n')
    lock_plugin(plugin)
    assert engine.run('demo-rule', invocation_id='drift')['status'] == 'blocked'
    assert not runner.calls


def test_action_formatting_keeps_hash_but_body_change_invalidates(tmp_path):
    engine, rule, runner, _, action_dir = setup(tmp_path)
    original = engine.add(rule)
    engine.grant('demo-rule')
    action_path = action_dir / 'hello.json'
    action = json.loads(action_path.read_text())
    action_path.write_text(json.dumps(action,indent=4,sort_keys=True))
    assert engine.preview('demo-rule')['action_hash'] == original['action_hash']
    action['fields']['message'] = 'changed'
    action_path.write_text(json.dumps(action))
    assert engine.run('demo-rule', invocation_id='changed')['status'] == 'blocked'
    assert not runner.calls


def test_timezone_copied_and_existing_rule_not_changed(tmp_path):
    engine, rule, *_ = setup(tmp_path)
    rule['trigger'] = {'type':'cron','expression':'0 7 * * *'}
    added = engine.add(rule)
    assert added['trigger']['timezone'] == 'Asia/Shanghai'
    (engine.root / 'automation.yaml').write_text('schema_version: 1\ntimezone: UTC\n')
    assert engine.store.get_rule('demo-rule')['trigger']['timezone'] == 'Asia/Shanghai'


def test_cli_publication_cannot_spoof_plugin_source(tmp_path):
    engine, *_ = setup(tmp_path)
    with pytest.raises(ValueError):
        engine.publish({'type':'task.created','source_plugin':'example.echo'})
    event = engine.publish({'type':'task.created','resource_refs':{'task_id':'1'}})
    assert event['source_plugin'] == 'core.cli'


def test_host_handoff_reuses_run_and_step_request_ids(tmp_path):
    engine, rule, runner, *_ = setup(tmp_path,host=True)
    engine.add(rule)
    engine.grant('demo-rule')
    pending=engine.run('demo-rule',invocation_id='handoff')
    completed=engine.run('demo-rule',run_id=pending['run_id'],host=True)
    assert completed['status']=='succeeded'
    assert completed['run_id']==pending['run_id']
    assert len(runner.calls)==1
    assert engine.run('demo-rule',run_id=pending['run_id'],host=True)['status']=='succeeded'
    assert len(runner.calls)==1


def test_event_trigger_exact_source_and_delivery_dedupe(tmp_path):
    engine, rule, runner, *_ = setup(tmp_path)
    rule.update(enabled=True,trigger={'type':'event','source':'core.cli','event_type':'demo.created'})
    engine.add(rule)
    engine.grant('demo-rule')
    event=engine.publish({'id':'event-test','type':'demo.created'})
    assert engine.tick()['runs'][0]['status']=='succeeded'
    assert engine.tick()['runs']==[]
    engine.store.publish_event(event)
    assert engine.tick()['runs']==[]
    assert len(runner.calls)==1


def test_tick_recovers_queued_event_after_crash_before_execution(tmp_path):
    engine,rule,runner,*_=setup(tmp_path)
    rule.update(enabled=True,trigger={'type':'event','source':'core.cli','event_type':'demo.created'})
    engine.add(rule)
    engine.grant('demo-rule')
    engine.publish({'type':'demo.created'})
    first=engine.tick(execute=False)['runs'][0]
    assert first['status']=='pending'
    resumed=engine.tick()['runs'][0]
    assert resumed['run_id']==first['run_id']
    assert resumed['status']=='succeeded'
    assert len(runner.calls)==1


def test_disabling_rule_stops_queued_automatic_occurrence(tmp_path):
    engine,rule,runner,*_=setup(tmp_path)
    rule.update(enabled=True,trigger={'type':'event','source':'core.cli','event_type':'demo.created'})
    engine.add(rule)
    engine.grant('demo-rule')
    engine.publish({'type':'demo.created'})
    run=engine.tick(execute=False)['runs'][0]
    engine.store.set_enabled('demo-rule',False)
    assert engine._execute(run)['status']=='blocked'
    assert not runner.calls


def test_interval_misfire_skip_and_latest(tmp_path):
    engine,rule,runner,*_=setup(tmp_path)
    rule.update(enabled=True,trigger={'type':'interval','seconds':300,'anchor':'2026-10-05T00:00:00Z'})
    engine.add(rule)
    engine.grant('demo-rule')
    engine.clock=lambda:'2026-10-05T00:12:00Z'
    runs=engine.tick()['runs']
    assert [r['status'] for r in runs]==['misfire_skipped','misfire_skipped']
    assert not runner.calls
    rule['misfire_policy']='latest'
    engine.clock=lambda:'2026-10-05T00:00:00Z'
    engine.add(rule)
    engine.grant('demo-rule')
    engine.clock=lambda:'2026-10-05T00:12:00Z'
    runs=engine.tick()['runs']
    assert [r['status'] for r in runs]==['misfire_skipped','succeeded']
    assert len(runner.calls)==1


def test_queued_time_trigger_does_not_run_outside_misfire_window(tmp_path):
    engine,rule,runner,*_=setup(tmp_path)
    rule.update(enabled=True,trigger={'type':'interval','seconds':300,'anchor':'2026-10-05T00:00:00Z'})
    engine.add(rule)
    engine.grant('demo-rule')
    engine.clock=lambda:'2026-10-05T00:05:00Z'
    queued=engine.tick(execute=False)['runs'][0]
    engine.clock=lambda:'2026-10-05T00:12:00Z'
    assert engine._execute(queued)['status']=='misfire_skipped'
    assert not runner.calls


def test_expired_grant_stops_before_plugin(tmp_path):
    engine,rule,runner,*_=setup(tmp_path)
    engine.add(rule)
    engine.grant('demo-rule')
    engine.clock=lambda:'2026-11-04T00:00:00Z'
    assert engine.run('demo-rule',invocation_id='expired')['status']=='blocked'
    assert not runner.calls


def test_worker_recovers_expired_dispatched_as_unknown_without_replaying(tmp_path):
    engine,rule,runner,*_=setup(tmp_path)
    stored=engine.add(rule)
    engine.grant('demo-rule')
    run=engine.store.enqueue_run(stored,'manual:crashed',engine.now())
    lease=engine.store.claim_run(run['run_id'],'dead-worker',engine.now())
    engine.store.mark_dispatched(run['run_id'],'dead-worker',lease['lease_generation'],engine.now())
    engine.clock=lambda:'2026-10-05T00:01:00Z'
    engine.worker(max_ticks=1)
    assert engine.store.show_run(run['run_id'])['status']=='unknown'
    assert not runner.calls


def test_unknown_workflow_manual_resolution_then_explicit_resume(tmp_path):
    from yushuos_sdk import StateStore
    engine,rule,runner,_,actions=setup(tmp_path)
    ledger=engine.root/'operations.sqlite3'
    state=StateStore(ledger)
    with state.connect(write=True):
        pass
    write_config(engine.root,{'state':{'ledger_path':'operations.sqlite3'}})
    action={'steps':[{'step_id':'first','capability':'example.echo','intent':'read','fields':{'message':'a'}},
        {'step_id':'second','capability':'example.echo','intent':'read','fields':{'message':'b'},'depends_on':['first']}]}
    (actions/'hello.json').write_text(json.dumps(action))
    def invoke(binding,request,**kwargs):
        runner.calls.append(request.request_id)
        state.claim(request)
        result=Result('unknown' if len(runner.calls)==1 else 'succeeded',request.request_id)
        state.record(result)
        return result
    runner.invoke=invoke
    engine.add(rule)
    engine.grant('demo-rule')
    run=engine.run('demo-rule',invocation_id='resolve')
    assert run['status']=='unknown'
    assert len(runner.calls)==1
    engine.resolve(runner.calls[0],'verified_success',reason_code='remote_readback',evidence_ref='record-1')
    assert engine.store.show_run(run['run_id'])['status']=='unknown'
    assert len(runner.calls)==1
    result=engine.run('demo-rule',run_id=run['run_id'],host=True)
    assert result['status']=='succeeded'
    assert len(runner.calls)==2
    assert state.effective_receipt(runner.calls[0])['original_status']=='unknown'


def test_expired_worker_cannot_checkpoint_or_start_next_workflow_step(tmp_path):
    from yushuos_sdk import StateStore
    engine,rule,runner,_,actions=setup(tmp_path)
    state=StateStore(engine.root/'operations.sqlite3')
    with state.connect(write=True):
        pass
    write_config(engine.root,{'state':{'ledger_path':'operations.sqlite3'}})
    action={'steps':[{'step_id':'first','capability':'example.echo','intent':'read','fields':{'message':'a'}},
        {'step_id':'second','capability':'example.echo','intent':'read','fields':{'message':'b'},'depends_on':['first']}]}
    (actions/'hello.json').write_text(json.dumps(action))
    def invoke(binding,request,**kwargs):
        runner.calls.append(request.request_id)
        engine.clock=lambda:'2026-10-05T00:01:00Z'
        run=engine.store.list_runs(status='running')[0]
        assert engine.store.claim_run(run['run_id'],'new-worker',engine.now()) is None
        return Result('succeeded',request.request_id)
    runner.invoke=invoke
    engine.add(rule)
    engine.grant('demo-rule')
    result=engine.run('demo-rule',invocation_id='fenced')
    assert result['status']=='unknown'
    assert result['error_code']=='dispatched_lease_expired'
    assert len(runner.calls)==1
    plan=engine.runtime.build_plan(engine._requests({'project_ref':'','steps':action['steps']},result['run_id']))
    assert state.workflow(plan.plan_id)['steps'][0]['status']=='running'


def test_active_pointer_read_failure_releases_undispatched_lease(tmp_path,monkeypatch):
    engine,rule,runner,*_=setup(tmp_path)
    stored=engine.add(rule)
    engine.grant('demo-rule')
    pending=engine.store.enqueue_run(stored,'manual:read-failure',engine.now())
    active=engine.root/'active.json'
    active.touch()
    read=Path.read_bytes
    def fault(path):
        if path==active:
            raise OSError('private failure detail')
        return read(path)
    monkeypatch.setattr(Path,'read_bytes',fault)
    result=engine._execute(pending)
    assert result['status']=='blocked'
    assert result['lease_owner'] is None
    assert not runner.calls
