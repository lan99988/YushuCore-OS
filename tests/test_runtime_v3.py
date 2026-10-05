import json
import subprocess

from test_automation_engine import setup
from yushuos.runtime import CoreRuntime
from yushuos_sdk.context import PluginContext


def test_runner_passes_valid_bound_v3_context(tmp_path):
    engine, _, _, *_ = setup(tmp_path)
    runtime = CoreRuntime(engine.root)
    captured=[]
    def invoke(args, **kwargs):
        value=json.loads(kwargs['input'])
        captured.append(value)
        return subprocess.CompletedProcess(args,0,json.dumps({'status':'succeeded','request_id':value['request']['request_id'],
            'message':'','resource':{},'data':{'received':'ok'},'error':None}),'')
    runtime.runner.run=invoke
    runtime.invoke({'request_id':'context-test','capability':'example.echo','intent':'read','fields':{'message':'ok'}})
    assert captured[0]['protocol']=='json-stdio-v2'
    context=PluginContext.from_envelope(captured[0])
    assert context.plugin_id=='example.echo'
    assert context.request_id=='context-test'
    assert context.depth==0
    assert len(context.provider_digest)==64


def test_workflow_preview_exposes_v3_execution_mode(tmp_path):
    engine, _, _, *_ = setup(tmp_path,host=True)
    plan=engine.runtime.plan({'steps':[{'step_id':'one','request_id':'preview-one','capability':'example.echo',
        'intent':'read','fields':{'message':'x'}}]})
    assert plan['steps'][0]['execution_mode']=='host_required'
