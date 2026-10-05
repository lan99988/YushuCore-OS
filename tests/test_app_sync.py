import hashlib
import json
import subprocess
import sys

import yaml

from yushuos.deployment import sync_app_plugin


def test_generic_app_sync_uses_explicit_descriptor_not_capability_name(tmp_path,monkeypatch):
    app='demo'
    release=tmp_path/'app-release'
    release.mkdir()
    descriptor={'schema_version':1,'app':app,'version':'1.0.0','capabilities':[
        {'id':'demo.unusual','effect':'external_write','intent':'capture',
         'input_schema':{'type':'object'},'output_schema':{'type':'any'},
         'execution_mode':'standalone','auth':{'required':True,'scopes':['demo.write']},'resource_bindings':{}}]}
    (release/'app-descriptor.json').write_text(json.dumps(descriptor))
    (release/'app_plugins').mkdir()
    (release/'app_plugins'/'__main__.py').write_text('# fake local app\n')
    file_map={p.relative_to(release).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in release.rglob('*') if p.is_file()}
    (release/'manifest.json').write_text(json.dumps({'app':app,'version':'1.0.0','files':file_map}))
    config=tmp_path/'app-config.json'
    config.write_text('{}')
    ledger=tmp_path/'ledger.sqlite'
    ledger.touch()
    app_root=tmp_path/'apps'
    (app_root/app).mkdir(parents=True)
    pointer={'app':app,'version':'1.0.0','release':str(release),'config_file':str(config),
             'ledger_path':str(ledger),'python_executable':sys.executable}
    (app_root/app/'active.json').write_text(json.dumps(pointer))
    catalog={'app':app,'capabilities':[{'id':'demo.unusual','implemented':True,'verified':True,'authorized':True,'enabled':True}]}
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,0,json.dumps(catalog),''))
    result=sync_app_plugin(tmp_path/'core',app_root,app=app)
    manifest=yaml.safe_load((tmp_path/'core/plugins/app-demo/1.0.0/plugin.yaml').read_text(encoding='utf-8'))
    cap=manifest['capabilities'][0]
    assert result['descriptor_version']==1
    assert manifest['contract_version']==3
    assert cap['effect']=='external_write'
    assert cap['execution_mode']=='standalone'
    assert cap['permissions']==['demo.write']
