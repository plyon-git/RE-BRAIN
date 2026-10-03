#!/usr/bin/env python3
"""Optional official-source refresh. Source text stays in a separate local cache.

Does not generate claims or assign profitable outcomes. No hosted AI dependency.
Known official hosts only, HTTPS, conservative robots policy, bounded files,
contact-bearing user agent, one request per host per second, visible failures.
"""
import argparse
import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED = {'sec.gov','investors.avalonbay.com','occ.gov','comptrollerofthecurrency.gov',
'consumerfinance.gov','irs.gov','epa.gov','hud.gov','fema.gov','census.gov','fhfa.gov',
'fanniemae.com','freddiemac.com','denvergov.org','trec.texas.gov','investor.gov','ftc.gov',
'foia.gov','nist.gov','scikit-learn.org','rfc-editor.org','energystar.gov','federalreserve.gov',
'scikit-survival.readthedocs.io','mlflow.org'}


def valid_url(url, resolve=True):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('Only credential-free HTTPS on port 443 is allowed')
    host=p.hostname.lower()
    if not any(host==x or host.endswith('.'+x) for x in APPROVED):
        raise ValueError('Host outside official-source allowlist: '+host)
    if resolve:
        for info in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise ValueError('Nonpublic destination address')
    return p


class Harvester:
    def __init__(self,user_agent,cache,interval=1.0,max_bytes=12*1024*1024):
        self.ua=user_agent
        self.cache=cache
        self.interval=max(1.0,interval)
        self.max_bytes=max_bytes
        self.last={}
        self.robots={}
        self.opener=urllib.request.build_opener(urllib.request.HTTPHandler(),urllib.request.HTTPSHandler(),NoRedirect())

    def rate(self,host):
        wait=self.interval-(time.monotonic()-self.last.get(host,0))
        if wait>0:time.sleep(wait)
        self.last[host]=time.monotonic()

    def request(self,url,check_robots=True):
        for _ in range(6):
            parsed=valid_url(url)
            if check_robots and not self.allowed(url): raise ValueError('Robots policy does not permit retrieval or could not be verified')
            self.rate(parsed.hostname)
            req=urllib.request.Request(url,headers={'User-Agent':self.ua,'Accept':'text/html,application/pdf,application/json,text/plain;q=0.8','Accept-Encoding':'identity'})
            try:
                response=self.opener.open(req,timeout=30)
            except urllib.error.HTTPError as e:
                if e.code in (301,302,303,307,308):
                    location=e.headers.get('Location')
                    if not location:raise ValueError('Redirect without Location')
                    url=urllib.parse.urljoin(url,location)
                    valid_url(url)
                    continue
                # No evasive proxy, alternate user agent, or automatic retry on 403/429.
                raise
            with response:
                n=response.headers.get('Content-Length')
                if n and int(n)>self.max_bytes:raise ValueError('Source exceeds configured byte limit; retrieve manually')
                body=response.read(self.max_bytes+1)
                if len(body)>self.max_bytes:raise ValueError('Source exceeds configured byte limit; retrieve manually')
                return body,dict(response.headers),url,response.status
        raise ValueError('Too many redirects')

    def allowed(self,url):
        p=valid_url(url)
        origin=f'https://{p.netloc}'
        if origin not in self.robots:
            robots_url=origin+'/robots.txt'
            try:
                body,_,_,status=self.request(robots_url,check_robots=False)
                parser=urllib.robotparser.RobotFileParser()
                parser.parse(body.decode('utf-8',errors='replace').splitlines())
                self.robots[origin]=parser
            except urllib.error.HTTPError as e:
                self.robots[origin]=True if e.code==404 else False
            except Exception:
                self.robots[origin]=False
        policy=self.robots[origin]
        return policy if isinstance(policy,bool) else policy.can_fetch(self.ua,url)

    def harvest(self,s):
        record={'source_id':s['id'],'source_url':s['url'],'requested_utc':datetime.now(timezone.utc).isoformat()}
        try:
            body,headers,url,status=self.request(s['url'])
            digest=hashlib.sha256(body).hexdigest()
            content_type=headers.get('Content-Type','').lower()
            suffix='.pdf' if 'pdf' in content_type else '.json' if 'json' in content_type else '.html' if 'html' in content_type else '.txt'
            dest=self.cache/(s['id']+'-'+digest[:12]+suffix)
            dest.write_bytes(body)
            record.update(status='retrieved',http_status=status,final_url=url,sha256=digest,bytes=len(body),content_type=content_type,file=str(dest))
        except Exception as e:
            record.update(status='manual_or_retry_required',error_type=type(e).__name__,error=str(e)[:400])
        return record


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-agent',help='Genuine organization/application identifier plus contact email, e.g. 101XVC BRAIN research operations@your-domain.com')
    parser.add_argument('--cache',type=Path,default=Path.home()/'.cache'/'101xvc-brain'/'official-sources')
    parser.add_argument('--source-id',action='append',help='Retrieve only these source IDs; repeat as needed')
    parser.add_argument('--limit',type=int,default=8,help='Max sources this invocation; default 8')
    parser.add_argument('--interval',type=float,default=1.0,help='Minimum seconds between host requests; cannot be below 1')
    parser.add_argument('--dry-run',action='store_true',help='List targets and validate metadata without network or cache writes')
    args=parser.parse_args()
    sources=json.loads((ROOT/'_data/sources.json').read_text())
    if args.source_id:sources=[s for s in sources if s['id'] in args.source_id]
    sources=sources[:max(0,args.limit)]
    if args.dry_run:
        for s in sources:valid_url(s['url'],resolve=False)
        print(json.dumps([{'id':s['id'],'url':s['url']} for s in sources],indent=2))
        return
    if not args.user_agent or '@' not in args.user_agent or '\n' in args.user_agent or '\r' in args.user_agent:
        parser.error('--user-agent must be a genuine organization/application identifier and contact email')
    args.cache.mkdir(parents=True,exist_ok=True)
    harvester=Harvester(args.user_agent,args.cache,args.interval)
    records=[]
    for s in sources:
        result=harvester.harvest(s)
        records.append(result)
        print(json.dumps({'source_id':s['id'],'status':result['status'],'bytes':result.get('bytes')}),flush=True)
    output=args.cache/('harvest-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    output.write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps({'manifest':str(output),'retrieved':sum(r['status']=='retrieved' for r in records),'total':len(records)}))

if __name__=='__main__':main()
