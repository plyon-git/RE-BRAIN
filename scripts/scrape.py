#!/usr/bin/env python3
"""Independent, bounded HTML-table property-record scraper and local preprocessor."""
import argparse
import csv
import hashlib
import io
import json
import math
import sys
import time
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.api.app import fetch_public

class Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None;self.depth=0
    def handle_starttag(self,tag,attrs):
        if tag=='table':
            self.depth+=1
            if self.depth==1:self.table=[]
        elif self.depth==1 and tag=='tr':self.row=[]
        elif self.depth==1 and tag in ('td','th'):self.cell=[]
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if self.depth==1 and tag in ('td','th') and self.cell is not None:
            if self.row is not None:self.row.append(' '.join(' '.join(self.cell).split()))
            self.cell=None
        elif self.depth==1 and tag=='tr' and self.row:
            self.table.append(self.row);self.row=None
        elif tag=='table' and self.depth:
            if self.depth==1:
                self.tables.append(self.table);self.table=None;self.row=None;self.cell=None
            self.depth-=1

def parse_tables(html):
    parser=Tables();parser.feed(html);return parser.tables

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--url');inputs.add_argument('--html-file')
    parser.add_argument('--table',type=int,default=0)
    parser.add_argument('--config',required=True,help='JSON source id/category/state/county_fips and mapping output field -> header')
    parser.add_argument('--output',required=True)
    parser.add_argument('--max-records',type=int,default=10000)
    parser.add_argument('--interval',type=float,default=1)
    parser.add_argument('--synthetic',action='store_true',help='Label every observation as a synthetic test fixture')
    args=parser.parse_args()
    if args.max_records < 1 or args.max_records > 10000:
        parser.error('--max-records must be between 1 and 10000')
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error('--interval must be a finite nonnegative number')
    source=json.loads(Path(args.config).read_text())
    if not isinstance(source,dict) or not isinstance(source.get('mapping',{}),dict):
        parser.error('Source configuration and mapping must be objects')
    if source.get('category') not in {'assessor','recorder','zoning','market'} or not source.get('id'):
        parser.error('Source configuration requires id and supported category')
    if not isinstance(source.get('synthetic',False),bool):
        parser.error('Source synthetic flag must be a boolean')
    synthetic = args.synthetic or source.get('synthetic',False)
    if args.url:
        parts=urlsplit(args.url)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:
            parser.error('A public HTTPS URL without credentials is required')
        robots=RobotFileParser(parts.scheme+'://'+parts.netloc+'/robots.txt')
        try:
            robots.parse(fetch_public(robots.url).decode('utf-8',errors='replace').splitlines())
        except HTTPError as exc:
            if exc.code == 404:
                robots.allow_all = True
            else:
                parser.error('Publisher robots rules could not be verified: '+str(exc))
        except (OSError,ValueError) as exc:
            parser.error('Public source URL or robots rules rejected: '+str(exc))
        if not robots.can_fetch('101XVC-BRAIN',args.url):parser.error('Publisher robots rules do not permit this path')
        delay=max(1,args.interval,robots.crawl_delay('101XVC-BRAIN') or 0)
        time.sleep(delay)
        try:
            raw=fetch_public(args.url)
        except (OSError,ValueError) as exc:
            parser.error('Public source fetch failed: '+str(exc))
        html=raw.decode('utf-8',errors='replace')
    else:html=Path(args.html_file).read_text()
    tables=parse_tables(html)
    if not 0<=args.table<len(tables) or len(tables[args.table])<2:parser.error('Requested table has no header and data rows')
    header=tables[args.table][0];mapping=source.get('mapping',{})
    if not all(header) or len(set(header))!=len(header):
        parser.error('Table headers must be unique and nonempty')
    if any(len(row)!=len(header) for row in tables[args.table][1:args.max_records+1]):
        parser.error('Table row lengths differ from the header; merged or malformed cells require preprocessing')
    observed=datetime.now(timezone.utc).isoformat()
    core={'parcel_id','address','state','county_fips','source_record_id'}
    count=0
    with Path(args.output).open('w') as output:
        for cells in tables[args.table][1:args.max_records+1]:
            row=dict(zip(header,cells))
            mapped={field:row.get(column,'') for field,column in mapping.items()}
            record={'source_id':source['id'],'category':source['category'],'county_fips':source.get('county_fips',''),
                    'state':source.get('state',''),'observed_at':observed,'synthetic':synthetic,'attributes':{'raw':row,'source_url':args.url or 'local HTML input'}}
            record.update({k:v for k,v in mapped.items() if k in core})
            record['source_record_id']=mapped.get('source_record_id') or hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
            for field,value in mapped.items():
                if field in core:continue
                if field in ('assessed_value','estimated_value','debt','sale_price','square_feet','bedrooms','bathrooms'):
                    try:value=float(value.replace('$','').replace(',',''))
                    except ValueError:continue
                record['attributes'][field]=value
            output.write(json.dumps(record)+'\n');count+=1
    print(json.dumps({'records':count,'output':str(Path(args.output).resolve()),'tables_found':len(tables),'synthetic':synthetic}))

if __name__=='__main__':main()
