"""Local content-addressed object storage for evidence and transaction documents."""
import base64
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

class DocumentStore:
    def __init__(self, root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()

    def put(self, data):
        if not isinstance(data,dict):raise ValueError('Document must be an object')
        name=data.get('filename','')
        if not isinstance(name,str) or not name or len(name)>200 or any(c in name for c in '\\/:\x00\r\n'):
            raise ValueError('Filename must be a plain filename under 200 characters')
        encoded=data.get('content_base64')
        if not isinstance(encoded,str) or len(encoded)>14_000_000:raise ValueError('Document must be Base64 encoded and below 10 MiB')
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):raise ValueError('Invalid Base64 document') from None
        if not raw or len(raw)>10*1024*1024:raise ValueError('Document must be between 1 byte and 10 MiB')
        media=data.get('media_type','application/octet-stream')
        if not isinstance(media,str) or not re.fullmatch(r'[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+',media):
            raise ValueError('Invalid media type')
        link={k:data[k] for k in ('property_id','episode_id') if data.get(k)}
        if any(not isinstance(v,str) or len(v)>200 for v in link.values()):raise ValueError('Document link identifiers must be strings below 200 characters')
        sha=hashlib.sha256(raw).hexdigest()
        meta_path=self.root/(sha+'.json')
        blob_path=self.root/(sha+'.blob')
        with self.lock:
            if meta_path.exists():
                meta=json.loads(meta_path.read_text())
                if link not in meta['links']:meta['links'].append(link)
            else:
                meta={'id':sha,'sha256':sha,'filename':name,'media_type':media,'bytes':len(raw),
                      'created_at':datetime.now(timezone.utc).isoformat(),'links':[link]}
                temp=blob_path.with_suffix('.tmp')
                temp.write_bytes(raw);os.replace(temp,blob_path)
            temp=meta_path.with_suffix('.tmp')
            temp.write_text(json.dumps(meta,indent=2));os.replace(temp,meta_path)
        return meta

    def list(self,property_id=None):
        with self.lock:
            items=[]
            for path in sorted(self.root.glob('*.json')):
                meta=json.loads(path.read_text())
                if not property_id or any(link.get('property_id')==property_id for link in meta['links']):items.append(meta)
            return {'items':items}

    def get(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{64}',identifier):raise ValueError('Document id must be a SHA256 digest')
        with self.lock:
            path=self.root/(identifier+'.json')
            if not path.exists():raise ValueError('Document not found')
            meta=json.loads(path.read_text());raw=(self.root/(identifier+'.blob')).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=identifier:raise ValueError('Document integrity check failed')
            return {**meta,'content_base64':base64.b64encode(raw).decode()}
