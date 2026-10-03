#!/usr/bin/env python3
"""Exercise real independent services, persistence, evidence, NLP and ML."""
import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--collector')
    parser.add_argument('--resolver')
    args=parser.parse_args()
    ports={name:port() for name in ['api','intelligence','collector','resolver']}
    urls={name:'http://127.0.0.1:'+str(p) for name,p in ports.items()}
    key='integration-only-token'
    def request(name,path,body=None,method=None,authorized=True):
        headers={'Content-Type':'application/json'}
        if authorized:headers['Authorization']='Bearer '+key
        req=Request(urls[name]+path,data=json.dumps(body).encode() if body is not None else None,
                    headers=headers,method=method)
        with urlopen(req,timeout=30) as response:
            raw=response.read()
            return json.loads(raw) if 'json' in response.headers.get('Content-Type','') else raw.decode()
    with tempfile.TemporaryDirectory() as folder:
        env=os.environ.copy()
        env.update(BRAIN_API_KEY=key,BRAIN_DB=str(Path(folder,'brain.sqlite3')),BRAIN_MODEL=str(Path(folder,'model.json')),
                   BRAIN_HOST='127.0.0.1',BRAIN_PORT=str(ports['api']),
                   BRAIN_INTELLIGENCE_HOST='127.0.0.1',BRAIN_INTELLIGENCE_PORT=str(ports['intelligence']),
                   INTELLIGENCE_URL=urls['intelligence'],COLLECTOR_PORT=str(ports['collector']),
                   BRAIN_RESOLVER_PORT=str(ports['resolver']))
        processes=[]
        handles=[]
        def launch(name,command):
            handle=open(Path(folder,name+'.log'),'w+')
            handles.append(handle)
            proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=handle,stderr=subprocess.STDOUT)
            processes.append(proc)
            for _ in range(150):
                if proc.poll() is not None:
                    handle.seek(0);raise RuntimeError(name+' exited: '+handle.read())
                try:
                    health=request(name,'/api/health' if name=='api' else '/health')
                    if health.get('status')=='ok':return proc
                except (URLError,HTTPError,ConnectionError):pass
                time.sleep(0.1)
            handle.seek(0);raise RuntimeError(name+' startup failed: '+handle.read())
        checks=[]
        try:
            launch('intelligence',[sys.executable,str(ROOT/'services/intelligence/server.py'),'--reference'])
            if args.collector:
                launch('collector',[str(Path(args.collector).resolve())]);env['COLLECTOR_URL']=urls['collector']
            if args.resolver:
                launch('resolver',[str(Path(args.resolver).resolve())]);env['RESOLVER_URL']=urls['resolver']
            api=launch('api',[sys.executable,str(ROOT/'services/api/app.py')])
            try:
                request('api','/api/stats',authorized=False)
                raise AssertionError('Authenticated deployment exposed private API')
            except HTTPError as exc:assert exc.code==401
            checks.append('API bearer authentication')
            request('api','/api/seed',{})
            first=request('api','/api/stats')
            request('api','/api/seed',{})
            assert request('api','/api/stats')['evidence']==first['evidence']==160
            prop=request('api','/api/properties')['items'][0]
            detail=request('api','/api/properties/'+prop['id'])
            assert len(detail['evidence'])==4 and detail['field_provenance']
            checks.append('idempotent cross-category property fusion and field provenance')
            request('api','/api/watchlist',{'property_id':prop['id']})
            assert request('api','/api/watchlist')['items']
            api.terminate();api.wait(timeout=5)
            launch('api',[sys.executable,str(ROOT/'services/api/app.py')])
            assert request('api','/api/watchlist')['items'][0]['id']==prop['id']
            checks.append('persistent database and watchlist across API restart')
            result=request('api','/api/underwrite',{'arv':100000,'purchase_price':60000,'repairs':10000,
                'holding_costs':2000,'closing_costs':2000,'selling_cost_pct':6,'partner_split_pct':50,'min_profit':20000})
            assert result['gross_profit']==20000 and result['company_share']==10000 and result['qualifies']
            checks.append('explicit underwriting and split arithmetic')
            model=request('api','/api/models')['models'][0]
            assert model['synthetic'] and model['trained_on']==3000
            prediction=request('api','/api/predict',{'features':{'equity_pct':0.8,'discount_pct':0.3,'ltv':0.2}})
            assert 0<=prediction['probability']<=1 and prediction['model_id']
            checks.append('trained local ML model prediction through API')
            knowledge=request('api','/api/knowledge?q=debt')
            assert knowledge['results'] and knowledge['method']=='local_tf_idf_cosine'
            checks.append('offline Obsidian TF-IDF retrieval through API')
            episode=request('api','/api/brain/episodes',{'property_id':prop['id'],'id':'integration-episode',
                'stage':'contracted','intake_date':'2026-09-01','contract_date':'2026-09-03',
                'asking_price':180000,'partner_id':'DEMO Partner','synthetic':True})['episode']
            episode_id=episode['id']
            request('api',f'/api/brain/episodes/{episode_id}/decisions',{'id':'integration-decision',
                'decision_at':'2026-09-01T12:00:00Z','prediction':{'closing_probability':None},
                'recommendation':{'action':'Verify title'},'action':'Requested ownership documents',
                'evidence_snapshot':{'features':{'sqft':1400,'assessed_value':200000,'offered_price':150000,
                    'stage':'contracted','state':prop['state'],'county_fips':prop['county_fips']}},'model_versions':{},'synthetic':True})
            offer={'id':'integration-offer','type':'offer','observed_at':'2026-09-02T12:00:00Z',
                'available_at':'2026-09-02T12:00:00Z','payload':{'price':150000,'response':'accepted','terms':{'closing_days':30}}}
            request('api',f'/api/brain/episodes/{episode_id}/events',offer)
            request('api',f'/api/brain/episodes/{episode_id}/events',offer)
            settlement={'type':'settlement','observed_at':'2026-09-22T12:00:00Z','available_at':'2026-09-22T12:00:00Z',
                'payload':{'closed_at':'2026-09-20T12:00:00Z','gross_spread':40000,'partner_share':20000,
                    'company_receipts':20000,'acquisition_costs':2500,'transaction_costs':1000,
                    'cash_received_at':'2026-09-22T12:00:00Z','cash_received':20000,'synthetic':True}}
            request('api',f'/api/brain/episodes/{episode_id}/events',settlement)
            request('api',f'/api/brain/episodes/{episode_id}/events',{'type':'outcome',
                'observed_at':'2026-09-22T12:00:00Z','available_at':'2026-09-22T12:00:00Z',
                'payload':{'status':'closed','occurred_at':'2026-09-20T12:00:00Z','synthetic':True}})
            ledger=request('api',f'/api/brain/episodes/{episode_id}')
            assert len(ledger['offers'])==1 and len(ledger['decisions'])==1
            assert ledger['current_settlement']['collected_cash']==20000
            checks.append('permanent transaction events, idempotent offers, immutable decisions and settled cash')
            report=request('api',f'/api/brain/report/{prop["id"]}?episode_id={episode_id}')
            assert 'offer' in report and 'company_economics' in report and 'next_action' in report
            assert request('api','/api/brain/portfolio') and request('api','/api/brain/queue')
            checks.append('live underwriting report, portfolio economics and execution queue')
            candidate=request('api','/api/brain/models/train',{'kind':'closing','synthetic':True})
            assert candidate['synthetic'] and not candidate['gate']['eligible']
            try:
                request('api','/api/brain/models/promote',{'model_id':candidate['model_id']})
                raise AssertionError('Synthetic underwriting model was promoted')
            except HTTPError as exc:assert exc.code==400
            checks.append('ledger-derived censored/outcome labels and synthetic model promotion refusal')
            document=request('api','/api/documents',{'filename':'integration-title.txt','media_type':'text/plain',
                'property_id':prop['id'],'episode_id':episode_id,
                'content_base64':base64.b64encode(b'Synthetic title evidence fixture').decode()})
            assert request('api','/api/documents')['items']
            downloaded=request('api','/api/documents/'+document['id'])
            assert base64.b64decode(downloaded['content_base64'])==b'Synthetic title evidence fixture'
            checks.append('content-addressed linked document integrity and export')
            if args.resolver:
                identity=request('resolver','/resolve',{'records':[{'county_fips':'48439','parcel_id':'000-012','address':'123 Main St','state':'TX'}]})
                assert identity['results'][0]['property_id']=='48439-000012'
                checks.append('compiled Rust HTTP resolver preserves parcel leading zeros')
            if args.collector:
                source={'id':'integration-collector','name':'Integration CSV fixture','category':'assessor',
                        'state':'TX','county_fips':'48439','adapter':'csv','mapping':{'source_record_id':'record_id'}}
                result=request('collector','/collect',{'source':source,
                    'csv_text':'record_id,parcel_id,address,owner,assessed_value\nfixture-1,000-012,123 Main St,Fixture Owner,250000\n'})
                assert result['count']==1 and result['records'][0]['parcel_id']=='000-012'
                request('api','/api/sources',{**source,'adapter':'manual'})
                record=result['records'][0];record['synthetic']=True
                assert request('api','/api/ingest',{'records':[record]})['accepted']==1
                assert request('api','/api/properties/48439-000012')['property']['owner']=='Fixture Owner'
                checks.append('compiled Go CSV collection to Rust identity and persistent Python fusion')
            assert '101XVC' in request('api','/')
            checks.append('standalone branded browser application served locally')
            print(json.dumps({'status':'passed','checks':checks,'real_services':
                ['python_api','python_intelligence']+(['go_collector'] if args.collector else [])+(['rust_resolver'] if args.resolver else [])},indent=2))
        except Exception:
            for handle in handles:
                handle.flush();handle.seek(0);print(handle.read()[-4000:],file=sys.stderr)
            raise
        finally:
            for proc in processes:
                if proc.poll() is None:proc.terminate()
            for proc in processes:
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            for handle in handles:handle.close()

if __name__=='__main__':main()
