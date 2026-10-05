import json

from test_automation_engine import setup
from yushuos.cli import main


def command(capsys, root, *args):
    code = main(['--config-root',str(root),*args])
    value = json.loads(capsys.readouterr().out)
    assert code == 0, value
    return value


def test_cli_rule_preview_grant_events_history(tmp_path,capsys):
    engine, rule, *_ = setup(tmp_path)
    path = tmp_path/'rule.json'
    path.write_text(json.dumps(rule))
    assert command(capsys,engine.root,'automation','add','--file',str(path))['id']=='demo-rule'
    assert len(command(capsys,engine.root,'automation','list')['rules'])==1
    assert command(capsys,engine.root,'automation','preview','--rule','demo-rule')['status']=='preview'
    assert command(capsys,engine.root,'automation','grant','--rule','demo-rule')['canonicalization']=='jcs-v1'
    assert command(capsys,engine.root,'automation','enable','--rule','demo-rule')['enabled'] is True
    event=tmp_path/'event.json'
    event.write_text(json.dumps({'type':'demo.created'}))
    published=command(capsys,engine.root,'events','publish','--file',str(event))
    assert published['source_plugin']=='core.cli'
    assert command(capsys,engine.root,'events','show','--event-id',published['id'])['id']==published['id']
    assert len(command(capsys,engine.root,'events','list')['events'])==1
    assert command(capsys,engine.root,'history','list')['runs']==[]
    assert 'execution_mode' in command(capsys,engine.root,'catalog','--details')['plugins'][0]['capabilities'][0]
