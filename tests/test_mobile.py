"""No-network tests for AI Study smartphone Netlify publishing."""
import importlib.util, io, json, tempfile, zipfile
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release_files'))
from unittest import mock

spec=importlib.util.spec_from_file_location('lp','release_files/live_progress.py')
lp=importlib.util.module_from_spec(spec);spec.loader.exec_module(lp)
# Tested separately by test_trophies.py; this test uses intentionally minimal HTML fixtures.
lp.trophies.install=lambda study: False

assert lp.mobile_site_host('spectacular-medovik-6118c6.netlify.app')=='spectacular-medovik-6118c6.netlify.app'
assert lp.mobile_site_host('https://spectacular-medovik-6118c6.netlify.app/')=='spectacular-medovik-6118c6.netlify.app'
for bad in ('https://example.org','http://spectacular-medovik-6118c6.netlify.app',
            'https://a.netlify.app.evil.org','https://a.netlify.app/other',
            'https://a.netlify.app?key=abc'):
    try:lp.mobile_site_host(bad)
    except ValueError:pass
    else:raise AssertionError('unsafe hostname accepted: '+bad)

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)
    cfg,study,out=root/'work'/'mobile_sync',root/'AI_Study',root/'work'/'outputs'
    cfg.mkdir(parents=True);study.mkdir();out.mkdir(parents=True)
    lp.mobile_paths=lambda:(cfg,study,out)
    def example(qid,question='Example of how AWS works'):
        return {'id':qid,'question':question}
    arr=[example('SAA-ORIG-0001')]
    pack={'questions':arr,'schema_version':1}
    (study/'questions.json').write_text(json.dumps(pack),encoding='utf-8')
    (study/'index.html').write_text('<html><script id="default-pack" type="application/json">'+json.dumps(pack)+'</script></html>',encoding='utf-8')
    (study/'sw.js').write_text("const CACHE='ai-study-vtest';",encoding='utf-8')
    (study/'manifest.webmanifest').write_text('{"name":"AI Study"}',encoding='utf-8')
    (study/'icon.svg').write_text('<svg/>',encoding='utf-8')
    binary,count=lp.build_mobile_zip(study)
    assert count==1
    with zipfile.ZipFile(io.BytesIO(binary)) as z:
        assert {'index.html','questions.json','sw.js','manifest.webmanifest'}<=set(z.namelist())
        assert not any('work/' in n or '.dpapi' in n for n in z.namelist())
        assert json.loads(z.read('questions.json'))==pack

    cfg_path=cfg/'config.json'
    cfg_path.write_text(json.dumps({
        'host':'spectacular-medovik-6118c6.netlify.app',
        'site_id':'aaa-bbb-ccc','token_dpapi':'fake-cipher-for-test'
    }),encoding='utf-8')
    calls=[]
    def mock_request(path,token,method='GET',data=None):
        assert token=='fake-token'
        calls.append((path,method,len(data or b'')))
        if path=='/sites/aaa-bbb-ccc':
            return {'id':'aaa-bbb-ccc','ssl_url':'https://spectacular-medovik-6118c6.netlify.app'}
        if path=='/sites/aaa-bbb-ccc/deploys':
            assert method=='POST' and data
            return {'id':'deploy-123','state':'ready'}
        raise AssertionError('Unknown simulated API request '+path)
    lp.dpapi_decrypt_token=lambda cipher:'fake-token'
    lp.mobile_request=mock_request
    res=lp.publish_mobile(force=True)
    assert res['status']=='PUBLISHED' and res['questions']==1
    assert len(calls)==2 and calls[1][1]=='POST'
    res=lp.publish_mobile()
    assert res['status']=='UP_TO_DATE' and len(calls)==2

    (study/'index.html').write_text('broken PWA',encoding='utf-8')
    try:lp.build_mobile_zip(study)
    except ValueError:pass
    else:raise AssertionError('Broken PWA must not be deployed')
    (study/'index.html').write_text('<script id="default-pack" type="application/json">'+json.dumps({'questions':[example('DIFFERENT')]})+'</script>',encoding='utf-8')
    try:lp.build_mobile_zip(study)
    except ValueError:pass
    else:raise AssertionError('Inconsistent PWA must not be deployed')

    (study/'index.html').write_text('<script id="default-pack" type="application/json">'+json.dumps(pack)+'</script>',encoding='utf-8')
    (cfg/'last_deploy.json').unlink()
    def wrong_site(*args,**kwargs):return {'id':'aaa-bbb-ccc','ssl_url':'https://another.netlify.app'}
    lp.mobile_request=wrong_site
    try:lp.publish_mobile()
    except ValueError:pass
    else:raise AssertionError('Wrong Netlify site should never be changed')

print('PASS: hostname validation, pack consistency, complete ZIP, no credentials in ZIP, mocked deploy, dedupe, wrong-site refusal')
