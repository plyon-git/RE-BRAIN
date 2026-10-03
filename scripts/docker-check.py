#!/usr/bin/env python3
"""Check the deployed Compose stack, including private service connectivity."""
import json
import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    key = os.environ['BRAIN_API_KEY']
    base = 'http://127.0.0.1:' + os.environ.get('BRAIN_PORT', '8080')

    def request(path, data=None, authenticated=True):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + key
        req = Request(base + path, headers=headers,
                      data=json.dumps(data).encode() if data is not None else None)
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    for attempt in range(150):
        try:
            if request('/api/health')['status'] == 'ok':
                break
        except (URLError, ConnectionError):
            pass
        time.sleep(.2)
    else:
        raise RuntimeError('Compose API did not become ready')
    try:
        request('/api/stats', authenticated=False)
    except HTTPError as exc:
        assert exc.code == 401, 'Expected authentication gate'
    else:
        raise AssertionError('Compose deployment exposed private data')
    request('/api/seed', {})
    assert request('/api/stats')['evidence'] == 160
    prop = request('/api/properties')['items'][0]
    report = request('/api/brain/report/' + prop['id'])
    assert report['company_economics']['expected_contribution'] is None
    search = request('/api/knowledge?q=debt%20service%20coverage')
    assert search['results'], 'Local knowledge service could not retrieve notes'
    models = request('/api/models')['models'][0]
    assert models['synthetic'] and models['trained_on'] == 3000
    code = '''import json,os,time
from urllib.request import Request,urlopen
key=os.environ['BRAIN_API_KEY']
for name,port in [('collector',8081),('resolver',8082),('intelligence',8083)]:
 for attempt in range(100):
  try:
   with urlopen('http://'+name+':'+str(port)+'/health',timeout=5) as response:
    assert json.load(response)['status']=='ok'
   break
  except Exception:
   if attempt==99:raise
   time.sleep(.2)
payload=json.dumps({'records':[{'county_fips':'48439','parcel_id':'000-012'}]}).encode()
req=Request('http://resolver:8082/resolve',data=payload,headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
with urlopen(req,timeout=10) as response:
 result=json.load(response)['results'][0]
 assert result['property_id']=='48439-000012',result
print('Private Go, Rust and local intelligence services passed')
'''
    subprocess.run(['docker', 'compose', 'exec', '-T', 'api', 'python3', '-c', code], check=True)
    print(json.dumps({'status': 'passed', 'docker_services': 4,
                      'authentication': True, 'local_model': True,
                      'knowledge_retrieval': True, 'underwriting_abstention': True}))


if __name__ == '__main__':
    main()
