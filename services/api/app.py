#!/usr/bin/env python3
"""101XVC BRAIN: dependency-free property data fusion API.

Run with `python3 services/api/app.py`. BRAIN_DB, BRAIN_HOST, BRAIN_PORT,
BRAIN_API_KEY, COLLECTOR_URL, and RESOLVER_URL configure the service.
All demo observations are explicitly synthetic. Money is a model estimate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import ipaddress
import json
import math
import mimetypes
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CATEGORIES = {"assessor", "recorder", "zoning", "market"}
STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
FIELDS = ("address", "owner", "assessed_value", "estimated_value", "debt", "zoning", "latitude", "longitude", "bedrooms", "bathrooms", "square_feet", "lot_size", "sale_price", "sale_date", "property_type", "repairs", "purchase_price", "holding_costs", "closing_costs", "selling_cost_pct")
NUMERIC_FIELDS = {"assessed_value", "estimated_value", "debt", "latitude", "longitude", "bedrooms", "bathrooms", "square_feet", "lot_size", "sale_price", "repairs", "purchase_price", "holding_costs", "closing_costs", "selling_cost_pct"}
PRIORITIES = {"owner": ["recorder", "assessor", "market", "zoning"], "debt": ["recorder", "assessor", "market", "zoning"], "estimated_value": ["market", "assessor", "recorder", "zoning"], "zoning": ["zoning", "assessor", "recorder", "market"], "assessed_value": ["assessor", "recorder", "market", "zoning"]}
MAX_BODY = 16 * 1024 * 1024
MAX_FETCH = 16 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def normalize_parcel(value):
    """Keep significant leading zeros; strip only punctuation and whitespace."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def address_key(address, state, county_fips):
    # No abbreviation guesses: unsafe address equivalence creates false merges.
    text = re.sub(r"[^A-Z0-9 ]", " ", str(address).upper())
    return " ".join(text.split()) + "|" + state


def resolve_record(record):
    parcel = normalize_parcel(record.get("parcel_id"))
    key = address_key(record.get("address", ""), record["state"], record["county_fips"])
    property_id = record["county_fips"] + "-" + parcel if parcel else record["county_fips"] + "-ADDR-" + hashlib.sha256(key.encode()).hexdigest()[:20]
    return {"property_id": property_id, "normalized_parcel_id": parcel or None, "address_key": key}


def finite_number(value, name, minimum=0):
    if isinstance(value, bool):
        raise ValueError(name + " must be a number")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(name + " must be a number") from None
    if not math.isfinite(result) or result < minimum:
        raise ValueError(name + " must be finite and >= " + str(minimum))
    return result


def underwrite(data):
    if not isinstance(data, dict):
        raise ValueError("underwriting must be an object")
    values = {key: finite_number(data.get(key, default), key) for key, default in {"arv": 0, "purchase_price": 0, "repairs": 0, "holding_costs": 0, "closing_costs": 0, "selling_cost_pct": 6, "partner_split_pct": 50, "min_profit": 20000}.items()}
    if values["selling_cost_pct"] > 100 or values["partner_split_pct"] > 100:
        raise ValueError("percentage values must be between 0 and 100")
    selling_costs = values["arv"] * values["selling_cost_pct"] / 100
    costs = values["purchase_price"] + values["repairs"] + values["holding_costs"] + values["closing_costs"] + selling_costs
    gross = values["arv"] - costs
    result = dict(values)
    result.update(selling_costs=round(selling_costs, 2), total_costs=round(costs, 2), gross_profit=round(gross, 2), company_share=round(gross * (1-values["partner_split_pct"]/100), 2), partner_share=round(gross * values["partner_split_pct"]/100, 2), qualifies=gross >= values["min_profit"], max_offer=round(values["arv"]-values["repairs"]-values["holding_costs"]-values["closing_costs"]-selling_costs-values["min_profit"], 2), margin_pct=round(gross/values["arv"]*100, 2) if values["arv"] else 0, model="estimated_transaction_spread", disclaimer="Underwritten estimates are not assured realized proceeds. Company share excludes company acquisition and operating expenses.")
    return result


def public_url(url):
    parsed = urllib.parse.urlsplit(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source URL must be an HTTP(S) URL without credentials")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("source URL port must be 80 or 443")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError("source host did not resolve") from None
    if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
        raise ValueError("source host must resolve only to public IP addresses")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirecting source URLs are rejected; register the final public URL")


def fetch_public(url):
    public_url(url)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "101XVC-BRAIN/1.0"}), timeout=15) as response:
        public_url(response.geturl())
        data = response.read(MAX_FETCH+1)
        if len(data) > MAX_FETCH:
            raise ValueError("source response exceeds 16 MiB; use the collector for bulk import")
        return data


def trusted_post(base, endpoint, data):
    url = base.rstrip("/") + endpoint
    headers = {"Content-Type": "application/json"}
    if os.environ.get("BRAIN_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["BRAIN_API_KEY"]
    req = urllib.request.Request(url, data=compact(data).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(MAX_FETCH+1)
            if len(raw) > MAX_FETCH:
                raise ValueError("service response too large")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(65536)).get("error",str(exc))
        except (ValueError,AttributeError):
            message = str(exc)
        raise ValueError("Local service rejected request: "+str(message)) from None


class IntelligenceGateway:
    """Use the local ML service, or the same engine in-process for one-command use."""
    def __init__(self):
        self.index = None
        self.model = None
        self.lock = threading.RLock()

    def request(self, endpoint, data=None):
        base = os.environ.get("INTELLIGENCE_URL")
        if base:
            if data is not None:
                return trusted_post(base, endpoint, data)
            headers = {}
            if os.environ.get("BRAIN_API_KEY"):
                headers["Authorization"] = "Bearer " + os.environ["BRAIN_API_KEY"]
            with urllib.request.urlopen(urllib.request.Request(base.rstrip("/")+endpoint,headers=headers),timeout=20) as response:
                return json.loads(response.read(MAX_FETCH+1))
        with self.lock:
            import sys
            project_root = Path(__file__).resolve().parents[2]
            engine_path = str(project_root / "services" / "intelligence")
            if engine_path not in sys.path:
                sys.path.insert(0,engine_path)
            try:
                from engine import KnowledgeIndex, OpportunityModel, extract
            except ImportError as exc:
                raise ValueError("intelligence engine is unavailable; start services/intelligence/app.py or configure INTELLIGENCE_URL") from exc
            if self.index is None:
                self.index = KnowledgeIndex(project_root / "knowledge" / "obsidian")
            if self.model is None:
                self.model = OpportunityModel(os.environ.get("BRAIN_MODEL",str(project_root / "runtime" / "model.json")))
            data = data or {}
            if endpoint == "/search": return self.index.search(data.get("query",""),data.get("limit",10))
            if endpoint == "/models": return self.model.status()
            if endpoint == "/predict": return self.model.predict(data.get("features",{}))
            if endpoint == "/train": return self.model.train(data.get("rows",[]),synthetic=data.get("synthetic",False))
            if endpoint == "/extract": return extract(data.get("text",""))
            raise ValueError("unsupported intelligence endpoint")


class UnderwritingGateway:
    """Lazily wire permanent transactions, measured models and report engine."""
    def __init__(self,store):
        self.store=store
        self.ledger=None
        self.registry=None
        self.engine=None
        self.documents=None

    def initialize(self):
        with self.store.lock:
            if self.engine is None:
                import sys
                root=Path(__file__).resolve().parents[2]
                if str(root) not in sys.path:sys.path.insert(0,str(root))
                from services.underwriting.ledger import TransactionLedger
                from services.underwriting.registry import ModelRegistry
                from services.underwriting.engine import UnderwritingEngine
                self.ledger=TransactionLedger(self.store.db,self.store.lock)
                self.registry=ModelRegistry(os.environ.get('BRAIN_REGISTRY',str(root/'runtime'/'underwriting-models')))
                self.engine=UnderwritingEngine(self.ledger,self.registry)
        return self

    def document_store(self):
        with self.store.lock:
            if self.documents is None:
                import sys
                root=Path(__file__).resolve().parents[2]
                if str(root) not in sys.path:sys.path.insert(0,str(root))
                from services.api.documents import DocumentStore
                self.documents=DocumentStore(os.environ.get('BRAIN_DOCUMENTS',str(Path(self.store.path).parent/'documents')))
        return self.documents


class BrainStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,state TEXT NOT NULL,county_fips TEXT NOT NULL,url TEXT NOT NULL,adapter TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS properties(id TEXT PRIMARY KEY,parcel_id TEXT,address TEXT NOT NULL,state TEXT NOT NULL,county_fips TEXT NOT NULL,data TEXT NOT NULL,updated_at TEXT NOT NULL,synthetic INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL REFERENCES sources(id),source_record_id TEXT NOT NULL,property_id TEXT NOT NULL REFERENCES properties(id),category TEXT NOT NULL,observed_at TEXT NOT NULL,record TEXT NOT NULL,UNIQUE(source_id,source_record_id));
          CREATE INDEX IF NOT EXISTS evidence_property_idx ON evidence(property_id);
          CREATE TABLE IF NOT EXISTS evidence_history(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),source_record_id TEXT NOT NULL,property_id TEXT NOT NULL REFERENCES properties(id),observed_at TEXT NOT NULL,available_at TEXT NOT NULL,recorded_at TEXT NOT NULL,record TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS evidence_history_property_idx ON evidence_history(property_id,recorded_at);
          CREATE TRIGGER IF NOT EXISTS evidence_history_no_update BEFORE UPDATE ON evidence_history BEGIN SELECT RAISE(ABORT,'Source evidence snapshots are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS evidence_history_no_delete BEFORE DELETE ON evidence_history BEGIN SELECT RAISE(ABORT,'Source evidence snapshots are permanent'); END;
          CREATE INDEX IF NOT EXISTS property_state_idx ON properties(state);
          CREATE INDEX IF NOT EXISTS property_county_idx ON properties(county_fips);
          CREATE INDEX IF NOT EXISTS property_updated_idx ON properties(updated_at DESC,id);
          CREATE INDEX IF NOT EXISTS evidence_category_property_idx ON evidence(category,property_id);
          CREATE TABLE IF NOT EXISTS watchlist(property_id TEXT PRIMARY KEY REFERENCES properties(id),added_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,details TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL REFERENCES sources(id),status TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,error TEXT,result TEXT);
        """)
        source_columns = {row[1] for row in self.db.execute("PRAGMA table_info(sources)")}
        for column in ("mapping", "options"):
            if column not in source_columns:
                self.db.execute("ALTER TABLE sources ADD COLUMN " + column + " TEXT NOT NULL DEFAULT '{}'")
        self.db.commit()

    def close(self):
        self.db.close()

    def activity(self, kind, message, details=None):
        self.db.execute("INSERT INTO activity(type,message,created_at,details) VALUES(?,?,?,?)", (kind, message, now(), compact(details or {})))

    def sources(self):
        with self.lock:
            return {"items": [self.source_item(row) for row in self.db.execute("SELECT * FROM sources ORDER BY created_at,id")]}

    @staticmethod
    def source_item(row):
        return dict(row, mapping=json.loads(row["mapping"]), options=json.loads(row["options"]))

    def add_source(self, data):
        if not isinstance(data, dict):
            raise ValueError("source must be an object")
        identifier = str(data.get("id") or "source-"+hashlib.sha256(compact(data).encode()).hexdigest()[:12])
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", identifier):
            raise ValueError("source id must contain 1 to 100 letters, digits, underscores, periods or hyphens")
        name = str(data.get("name", "")).strip()
        category = data.get("category")
        state = str(data.get("state", "")).upper()
        county = str(data.get("county_fips", ""))
        url = str(data.get("url", "")).strip()
        adapter = str(data.get("adapter", "manual")).lower()
        status = str(data.get("status", "configured"))
        if not name or category not in CATEGORIES or (state and state not in STATES) or (county and not re.fullmatch(r"[0-9]{5}", county)):
            raise ValueError("source requires name, valid category, optional two-letter US state and five-digit county_fips")
        if adapter not in {"manual", "csv", "json", "arcgis", "socrata", "collector"} or status not in {"configured", "planned"}:
            raise ValueError("adapter must be manual, csv, json, arcgis, socrata or collector; status must be configured or planned")
        mapping, options = data.get("mapping", {}), data.get("options", {})
        if not isinstance(mapping,dict) or not isinstance(options,dict):
            raise ValueError("source mapping and options must be objects")
        if adapter != "manual" and status == "configured" and not url:
            raise ValueError("configured remote adapters require a URL")
        if url:
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("source URL must use HTTP(S) without credentials")
        with self.lock, self.db:
            old = self.db.execute("SELECT * FROM sources WHERE id=?", (identifier,)).fetchone()
            if old and self.db.execute("SELECT 1 FROM evidence WHERE source_id=? LIMIT 1", (identifier,)).fetchone():
                if old["category"] != category or old["state"] != state or old["county_fips"] != county:
                    raise ValueError("source category and geographic scope cannot change after ingestion")
            self.db.execute("INSERT INTO sources(id,name,category,state,county_fips,url,adapter,status,created_at,mapping,options) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,category=excluded.category,state=excluded.state,county_fips=excluded.county_fips,url=excluded.url,adapter=excluded.adapter,status=excluded.status,mapping=excluded.mapping,options=excluded.options", (identifier,name,category,state,county,url,adapter,status,now(),compact(mapping),compact(options)))
            self.activity("source", "Source configured: " + name, {"source_id":identifier, "status":status})
            return self.source_item(self.db.execute("SELECT * FROM sources WHERE id=?", (identifier,)).fetchone())

    def update_source(self, identifier, data):
        with self.lock:
            current = self.db.execute("SELECT * FROM sources WHERE id=?", (identifier,)).fetchone()
            if current is None:
                raise ValueError("source_id does not exist")
            merged = dict(self.source_item(current),**data)
            merged["id"] = identifier
            return self.add_source(merged)

    def delete_source(self, identifier):
        with self.lock,self.db:
            if self.db.execute("SELECT 1 FROM evidence WHERE source_id=? LIMIT 1", (identifier,)).fetchone():
                raise ValueError("Source has retained evidence and cannot be deleted; set status to planned to disable collection while preserving provenance")
            # Jobs reference source configuration; completed job history is meaningful.
            if self.db.execute("SELECT 1 FROM jobs WHERE source_id=? LIMIT 1", (identifier,)).fetchone():
                raise ValueError("Source has retained job history and cannot be deleted; set status to planned to disable collection")
            removed = self.db.execute("DELETE FROM sources WHERE id=?", (identifier,)).rowcount
            if removed:
                self.activity("source", "Unreferenced source deleted", {"source_id":identifier})
            return {"deleted":bool(removed),"source_id":identifier}

    def prepare_records(self, payload):
        """Accept canonical observations or mapped CSV rows in a source envelope."""
        records = payload.get("records")
        if not isinstance(records,list):
            return records  # ingest reports the consistent array validation error
        prepared = []
        with self.lock:
            for record in records:
                if not isinstance(record,dict):
                    prepared.append(record)
                    continue
                row = dict(record)
                source_id = row.get("source_id") or payload.get("source_id")
                source = self.db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone() if source_id else None
                if source:
                    row.setdefault("source_id",source_id)
                    row.setdefault("category",source["category"])
                    row.setdefault("state",source["state"])
                    row.setdefault("county_fips",source["county_fips"])
                row.setdefault("observed_at",now())
                row.setdefault("synthetic",bool(payload.get("synthetic",False)))
                row.setdefault("attributes",{field:row[field] for field in FIELDS if field != "address" and field in row})
                if not row.get("source_record_id"):
                    row["source_record_id"] = "row-"+hashlib.sha256(compact(row.get("_raw_record",record)).encode()).hexdigest()[:32]
                prepared.append(row)
        return prepared

    def validate_record(self, data):
        if not isinstance(data, dict):
            raise ValueError("record must be an object")
        record = dict(data)
        required = ("source_id", "source_record_id", "county_fips", "state", "address", "category", "observed_at", "attributes")
        if any(key not in record for key in required):
            raise ValueError("required fields: " + ", ".join(required))
        record["state"] = str(record["state"]).upper()
        record["county_fips"] = str(record["county_fips"])
        if record["state"] not in STATES or not re.fullmatch(r"[0-9]{5}", record["county_fips"]):
            raise ValueError("state must be a two-letter US state; county_fips must be five digits (send identifiers as strings)")
        for key in ("source_id", "source_record_id", "address"):
            if not isinstance(record[key], str) or not record[key].strip() or len(record[key]) > 500:
                raise ValueError(key + " must be a nonempty string of at most 500 characters")
            record[key] = record[key].strip()
        if "parcel_id" in record and record["parcel_id"] is not None and not isinstance(record["parcel_id"], str):
            raise ValueError("parcel_id must be a string to preserve leading zeros")
        if len(str(record.get("parcel_id") or "").encode("utf-8")) > 128:
            raise ValueError("parcel_id must be at most 128 UTF-8 bytes")
        if record["category"] not in CATEGORIES or not isinstance(record["attributes"], dict):
            raise ValueError("category must be assessor, recorder, zoning or market; attributes must be an object")
        try:
            observed = datetime.fromisoformat(str(record["observed_at"]).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            record["observed_at"] = observed.astimezone(timezone.utc).isoformat(timespec="seconds")
        except (ValueError, TypeError):
            raise ValueError("observed_at must be an ISO 8601 datetime or date") from None
        recorded = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        try:
            available = datetime.fromisoformat(str(record.get('available_at') or recorded).replace('Z','+00:00'))
            if available.tzinfo is None:available=available.replace(tzinfo=timezone.utc)
            available=available.astimezone(timezone.utc)
        except (ValueError,TypeError):
            raise ValueError('available_at must be an ISO 8601 datetime or date') from None
        if available.timestamp()>time.time()+300:raise ValueError('available_at cannot be in the future')
        record['availability_basis']='provided_by_source' if data.get('available_at') else 'first_ingestion_receipt'
        record['available_at']=available.isoformat(timespec='microseconds')
        record['recorded_at']=recorded
        source = self.db.execute("SELECT * FROM sources WHERE id=?", (record["source_id"],)).fetchone()
        if not source:
            raise ValueError("source_id is not registered; configure it through /api/sources first")
        if source["category"] != record["category"] or (source["state"] and source["state"] != record["state"]) or (source["county_fips"] and source["county_fips"] != record["county_fips"]):
            raise ValueError("record category or geographic scope differs from registered source")
        record['source_snapshot']={key:source[key] for key in ('id','name','category','state','county_fips','url','adapter','status','created_at')}
        for field in NUMERIC_FIELDS:
            value = record["attributes"].get(field)
            if value is not None:
                record["attributes"][field] = finite_number(value, field, -180 if field in {"latitude", "longitude"} else 0)
        compact(record)  # Reject NaN or unserializable nested attributes too.
        record["synthetic"] = bool(record.get("synthetic", False))
        return record

    def ingest(self, records):
        if not isinstance(records, list) or len(records) > 10000:
            raise ValueError("records must be an array with at most 10000 records")
        result = {"accepted": 0, "rejected": 0, "errors": [], "properties": 0}
        affected = set()
        with self.lock, self.db:
            valid = []
            for index, record in enumerate(records):
                try:
                    valid.append((index, self.validate_record(record)))
                except (ValueError, TypeError) as exc:
                    result["rejected"] += 1
                    result["errors"].append({"index":index,"error":str(exc)})
            resolved = [resolve_record(record) for _, record in valid]
            if valid and os.environ.get("RESOLVER_URL"):
                try:
                    remote = trusted_post(os.environ["RESOLVER_URL"], "/resolve", {"records":[r for _,r in valid]})["results"]
                    # Resolver is an accelerator, not an authority for parcel identity.
                    if len(remote) != len(resolved) or any(remote[i].get("property_id") != resolved[i]["property_id"] for i in range(len(resolved))):
                        raise ValueError("resolver identity mismatch")
                    resolved = remote
                except (OSError, ValueError, KeyError, TypeError):
                    self.activity("resolver", "Resolver unavailable or incompatible; Python canonical resolver used")
            for (_, record), identity in zip(valid, resolved):
                property_id = identity["property_id"]
                old = self.db.execute("SELECT property_id FROM evidence WHERE source_id=? AND source_record_id=?", (record["source_id"], record["source_record_id"])).fetchone()
                if old and old["property_id"] != property_id:
                    result["rejected"] += 1
                    result["errors"].append({"index":_, "error":"source record identity cannot change parcels; use a new source_record_id"})
                    continue
                self.db.execute("INSERT OR IGNORE INTO properties VALUES(?,?,?,?,?,?,?,?)", (property_id, identity["normalized_parcel_id"], record["address"], record["state"], record["county_fips"], "{}", now(), int(record["synthetic"])))
                signature={k:v for k,v in record.items() if k not in {'recorded_at','available_at','evidence_version_id'}}
                if record['availability_basis']=='provided_by_source':signature['available_at']=record['available_at']
                version_id='evidence-'+hashlib.sha256(json.dumps(signature,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
                record['evidence_version_id']=version_id
                historic=self.db.execute('SELECT record FROM evidence_history WHERE id=?',(version_id,)).fetchone()
                if historic:
                    record=json.loads(historic['record'])
                else:
                    self.db.execute('INSERT INTO evidence_history VALUES(?,?,?,?,?,?,?,?)',(version_id,record['source_id'],record['source_record_id'],property_id,record['observed_at'],record['available_at'],record['recorded_at'],compact(record)))
                current=self.db.execute('SELECT record FROM evidence WHERE source_id=? AND source_record_id=?',(record['source_id'],record['source_record_id'])).fetchone()
                if current:
                    prior=json.loads(current['record'])
                    # A repeated old snapshot is retained without rewinding a newer feed observation.
                    prior_key=(prior.get('observed_at',''),prior.get('recorded_at',''))
                    next_key=(record['observed_at'],record['recorded_at'])
                    if next_key<prior_key:
                        result['accepted']+=1
                        affected.add(property_id)
                        continue
                self.db.execute("INSERT INTO evidence(source_id,source_record_id,property_id,category,observed_at,record) VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,source_record_id) DO UPDATE SET category=excluded.category,observed_at=excluded.observed_at,record=excluded.record", (record["source_id"],record["source_record_id"],property_id,record["category"],record["observed_at"],compact(record)))
                affected.add(property_id)
                result["accepted"] += 1
            for property_id in affected:
                self.rebuild(property_id)
            result["properties"] = len(affected)
            self.activity("ingest", "Accepted %d records across %d properties" % (result["accepted"], len(affected)), result)
        return result

    def evidence(self, property_id):
        return [dict(json.loads(row["record"]), evidence_id=row["id"], property_id=row["property_id"]) for row in self.db.execute("SELECT * FROM evidence WHERE property_id=? ORDER BY observed_at DESC,id DESC", (property_id,))]

    def evidence_history(self,property_id):
        return [dict(json.loads(row['record']),property_id=row['property_id']) for row in self.db.execute('SELECT * FROM evidence_history WHERE property_id=? ORDER BY recorded_at,id',(property_id,))]

    def rebuild(self, property_id):
        observations = self.evidence(property_id)
        data = {}
        provenance = {}
        conflicts = []
        for field in FIELDS:
            candidates = []
            for observation in observations:
                value = observation.get("address") if field == "address" else observation["attributes"].get(field)
                if value is not None and value != "":
                    candidates.append((observation, value))
            if not candidates:
                data[field] = None
                continue
            priority = PRIORITIES.get(field, ["assessor", "recorder", "market", "zoning"])
            candidates.sort(key=lambda item: (priority.index(item[0]["category"]), -datetime.fromisoformat(item[0]["observed_at"]).timestamp(), item[0]["source_id"], item[0]["source_record_id"]))
            observation, value = candidates[0]
            data[field] = value
            provenance[field] = {"source_id":observation["source_id"], "source_record_id":observation["source_record_id"], "category":observation["category"], "observed_at":observation["observed_at"], "evidence_id":observation["evidence_id"], "selection_rule":"category authority, then latest observation, then stable source identity"}
            provenance[field].update(available_at=observation.get('available_at'),recorded_at=observation.get('recorded_at'),evidence_version_id=observation.get('evidence_version_id'),availability_basis=observation.get('availability_basis','unknown'))
            distinct = {compact(candidate) for _,candidate in candidates}
            if len(distinct) > 1:
                conflicts.append({"field":field,"selected":value,"selected_source_id":observation["source_id"],"values":[{"value":candidate,"source_id":obs["source_id"],"source_record_id":obs["source_record_id"],"observed_at":obs["observed_at"]} for obs,candidate in candidates]})
        data["field_provenance"] = provenance
        data["conflicts"] = conflicts
        data["categories"] = sorted({observation["category"] for observation in observations})
        value = data.get("estimated_value") or data.get("assessed_value") or 0
        debt = data.get("debt") or 0
        risk = min(100, 15 + round(min(debt/value,2)*30) if value else 65)
        risk = min(100, risk + len(conflicts)*3 + (10 if len(data["categories"]) < 3 else 0))
        data["risk_score"] = risk
        data["score"] = max(0, min(100, 100-risk + len(data["categories"])*5))
        data["evidence_count"] = len(observations)
        data["synthetic"] = all(observation.get("synthetic",False) for observation in observations)
        data["updated_at"] = max(observation["observed_at"] for observation in observations)
        self.db.execute("UPDATE properties SET address=?,data=?,updated_at=?,synthetic=? WHERE id=?", (data["address"],compact(data),data["updated_at"],int(data["synthetic"]),property_id))

    def property_item(self, row):
        item = json.loads(row["data"])
        item.update(id=row["id"],parcel_id=row["parcel_id"],state=row["state"],county_fips=row["county_fips"],address=row["address"],synthetic=bool(row["synthetic"]))
        return item

    def properties(self, q="", state="", category="", limit=100, offset=0):
        with self.lock:
            clauses = []
            params = []
            if q:
                clauses.append("(address LIKE ? ESCAPE '\\' OR parcel_id LIKE ? ESCAPE '\\' OR data LIKE ? ESCAPE '\\')")
                needle = "%"+q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")+"%"
                params.extend([needle]*3)
            if state:
                clauses.append("state=?")
                params.append(state.upper())
            if category:
                if category not in CATEGORIES:
                    raise ValueError("invalid category")
                clauses.append("EXISTS (SELECT 1 FROM evidence e WHERE e.property_id=properties.id AND e.category=?)")
                params.append(category)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = self.db.execute("SELECT COUNT(*) FROM properties"+where, params).fetchone()[0]
            rows = self.db.execute("SELECT * FROM properties"+where+" ORDER BY updated_at DESC,id LIMIT ? OFFSET ?", params+[max(1,min(int(limit),10000)),max(0,int(offset))])
            return {"items":[self.property_item(row) for row in rows],"total":total}

    def default_underwriting(self, prop):
        arv = prop.get("estimated_value") or prop.get("assessed_value") or 0
        return underwrite({"arv":arv,"purchase_price":prop.get("purchase_price") if prop.get("purchase_price") is not None else arv*.62,"repairs":prop.get("repairs") if prop.get("repairs") is not None else arv*.12,"holding_costs":prop.get("holding_costs") if prop.get("holding_costs") is not None else 5000,"closing_costs":prop.get("closing_costs") if prop.get("closing_costs") is not None else 3000,"selling_cost_pct":prop.get("selling_cost_pct") if prop.get("selling_cost_pct") is not None else 6})

    def detail(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT * FROM properties WHERE id=?", (identifier,)).fetchone()
            if row is None:
                return None
            prop = self.property_item(row)
            evidence = self.evidence(identifier)
            peers = self.db.execute("SELECT * FROM properties WHERE county_fips=? AND id!=? LIMIT 200", (row["county_fips"],identifier))
            target_value = prop.get("estimated_value") or prop.get("assessed_value") or 0
            comps = [self.property_item(peer) for peer in peers]
            comps.sort(key=lambda item: abs((item.get("estimated_value") or item.get("assessed_value") or 0)-target_value))
            # These are candidates, not verified comparable sale selections.
            comps = [{"id":item["id"],"address":item["address"],"estimated_value":item.get("estimated_value"),"assessed_value":item.get("assessed_value"),"synthetic":item["synthetic"],"status":"candidate; verify sale date, condition and comparability","field_provenance":item.get("field_provenance",{})} for item in comps[:5]]
            return {"property":prop,"evidence":evidence,"evidence_history":self.evidence_history(identifier),"conflicts":prop["conflicts"],"field_provenance":prop["field_provenance"],"comps":comps,"underwriting":self.default_underwriting(prop)}

    def stats(self):
        with self.lock:
            category_counts = {category:self.db.execute("SELECT COUNT(DISTINCT property_id) FROM evidence WHERE category=?", (category,)).fetchone()[0] for category in sorted(CATEGORIES)}
            states = {row["state"]:row["n"] for row in self.db.execute("SELECT state,COUNT(*) AS n FROM properties GROUP BY state")}
            aggregate = self.db.execute("SELECT COUNT(*) AS n,COALESCE(SUM(json_array_length(data,'$.conflicts')),0) AS conflicts,COALESCE(SUM(synthetic),0) AS synthetic FROM properties").fetchone()
            return {"properties":aggregate["n"],"sources":self.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0],"evidence":self.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],"conflicts":aggregate["conflicts"],"watchlist":self.db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0],"category_counts":category_counts,"state_counts":states,"synthetic_properties":aggregate["synthetic"]}

    def watchlist(self):
        with self.lock:
            return {"items":[dict(self.property_item(row),added_at=row["added_at"],property_id=row["id"]) for row in self.db.execute("SELECT p.*,w.added_at FROM watchlist w JOIN properties p ON p.id=w.property_id ORDER BY w.added_at DESC,p.id")]}

    def add_watch(self, identifier):
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM properties WHERE id=?", (identifier,)).fetchone():
                raise ValueError("property_id does not exist")
            self.db.execute("INSERT OR IGNORE INTO watchlist VALUES(?,?)", (identifier,now()))
            self.activity("watchlist", "Property added to watchlist", {"property_id":identifier})
            return {"property_id":identifier,"status":"saved"}

    def delete_watch(self, identifier):
        with self.lock, self.db:
            deleted = self.db.execute("DELETE FROM watchlist WHERE property_id=?", (identifier,)).rowcount
            if deleted:
                self.activity("watchlist", "Property removed from watchlist", {"property_id":identifier})
            return {"deleted":bool(deleted)}

    def scout(self, state="", min_profit=20000, limit=500):
        threshold = finite_number(min_profit, "min_profit")
        limit = max(1,min(int(limit),10000))
        items = []
        # Rank the entire database before applying the response limit.
        arv = "COALESCE(NULLIF(json_extract(data,'$.estimated_value'),0),json_extract(data,'$.assessed_value'),0)"
        expr = f"({arv} - COALESCE(json_extract(data,'$.purchase_price'),{arv}*.62) - COALESCE(json_extract(data,'$.repairs'),{arv}*.12) - COALESCE(json_extract(data,'$.holding_costs'),5000) - COALESCE(json_extract(data,'$.closing_costs'),3000) - {arv}*COALESCE(json_extract(data,'$.selling_cost_pct'),6)/100.0)"
        where = " WHERE "+expr+">=?"
        params = [threshold]
        if state:
            where += " AND state=?"
            params.append(state.upper())
        with self.lock:
            total = self.db.execute("SELECT COUNT(*) FROM properties"+where,params).fetchone()[0]
            rows = self.db.execute("SELECT * FROM properties"+where+" ORDER BY json_extract(data,'$.score') DESC,"+expr+" DESC,id LIMIT ?",params+[limit])
            for row in rows:
                prop = self.property_item(row)
                model = underwrite(dict(self.default_underwriting(prop),min_profit=threshold))
                items.append(dict(prop,underwriting=model,estimated_profit=model["gross_profit"],company_share=model["company_share"],reason="Estimated spread meets the selected threshold; validate inputs before acquisition",provenance=prop["field_provenance"]))
        return {"items":items,"total_matches":total,"returned":len(items),"limit":limit,"truncated":total>len(items),"min_profit":threshold,"model":"deterministic_estimated_spread"}

    def activities(self):
        with self.lock:
            return {"items":[dict(row,details=json.loads(row["details"])) for row in self.db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 200")]}

    def jobs(self):
        with self.lock:
            return {"items":[dict(row,result=json.loads(row["result"]) if row["result"] else None) for row in self.db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100")]}

    def start_job(self, source_id, asynchronous=True):
        with self.lock, self.db:
            source = self.db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            if not source:
                raise ValueError("source_id does not exist")
            if source["status"] != "configured":
                raise ValueError("planned sources cannot run; configure an actual source URL first")
            identifier = self.db.execute("INSERT INTO jobs(source_id,status,started_at) VALUES(?,?,?)", (source_id,"queued",now())).lastrowid
            self.activity("job", "Collection job queued", {"job_id":identifier,"source_id":source_id})
        if asynchronous:
            threading.Thread(target=self.run_job,args=(identifier,self.source_item(source)),daemon=True).start()
        else:
            self.run_job(identifier,self.source_item(source))
        return {"id":identifier,"job_id":identifier,"status":"queued" if asynchronous else self.jobs()["items"][0]["status"],"source_id":source_id}

    def run_job(self, identifier, source):
        try:
            with self.lock,self.db:
                self.db.execute("UPDATE jobs SET status='running' WHERE id=?", (identifier,))
            if os.environ.get("COLLECTOR_URL"):
                # The source URL is still subject to public-host validation by the collector.
                records = trusted_post(os.environ["COLLECTOR_URL"], "/collect", {"source":source})["records"]
            elif source["adapter"] == "csv":
                records = []
                for index,row in enumerate(csv.DictReader(io.StringIO(fetch_public(source["url"]).decode("utf-8-sig")))):
                    if index >= 10000:
                        raise ValueError("CSV exceeds 10000 rows; split imports")
                    attrs = {key:row[key] for key in FIELDS if key != "address" and row.get(key) not in {None,""}}
                    records.append({"source_id":source["id"],"source_record_id":row.get("source_record_id") or row.get("OBJECTID") or str(index),"parcel_id":row.get("parcel_id"),"state":row.get("state") or source["state"],"county_fips":row.get("county_fips") or source["county_fips"],"address":row.get("address", ""),"category":source["category"],"observed_at":row.get("observed_at") or now(),"attributes":attrs})
            elif source["adapter"] == "arcgis":
                url = source["url"].rstrip("/")
                if not url.endswith("/query"):
                    url += "/query"
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"where":"1=1","outFields":"*","f":"json","resultRecordCount":1000})
                response = json.loads(fetch_public(url))
                if response.get("exceededTransferLimit"):
                    raise ValueError("ArcGIS requires pagination; use the Go collector to avoid a partial import")
                records = []
                for index,feature in enumerate(response.get("features", [])):
                    attrs = feature.get("attributes", {})
                    records.append({"source_id":source["id"],"source_record_id":str(attrs.get("source_record_id") or attrs.get("OBJECTID") or index),"parcel_id":attrs.get("parcel_id"),"state":attrs.get("state") or source["state"],"county_fips":attrs.get("county_fips") or source["county_fips"],"address":attrs.get("address", ""),"category":source["category"],"observed_at":attrs.get("observed_at") or now(),"attributes":{k:v for k,v in attrs.items() if k in FIELDS and k != "address"}})
            else:
                raise ValueError("This source is manual or requires COLLECTOR_URL; import observations through /api/ingest")
            result = self.ingest(records)
            with self.lock,self.db:
                self.db.execute("UPDATE jobs SET status=?,completed_at=?,result=? WHERE id=?", ("completed" if not result["rejected"] else "completed_with_errors",now(),compact(result),identifier))
                self.activity("job", "Collection job finished", {"job_id":identifier,"result":result})
        except Exception as exc:
            with self.lock,self.db:
                self.db.execute("UPDATE jobs SET status='failed',completed_at=?,error=? WHERE id=?", (now(),str(exc)[:1000],identifier))
                self.activity("job", "Collection job failed", {"job_id":identifier,"error":str(exc)[:1000]})

    def seed(self):
        # 40 canonical properties × four independent observation categories.
        for category in sorted(CATEGORIES):
            self.add_source({"id":"demo-"+category,"name":"Synthetic demo "+category,"category":category,"adapter":"manual","status":"configured"})
        locations = [("TX","48439","Fort Worth"),("FL","12086","Miami"),("AZ","04013","Phoenix"),("NC","37119","Charlotte"),("IL","17031","Chicago"),("CO","08031","Denver"),("GA","13121","Atlanta"),("TN","47157","Memphis")]
        records = []
        for index in range(40):
            state,county,city = locations[index%len(locations)]
            value = 185000 + index*7900
            parcel = "00"+str(index+10001)
            common = {"parcel_id":parcel,"state":state,"county_fips":county,"address":f"{100+index*7} Synthetic Demo Avenue, {city}, {state}","observed_at":"2026-09-15T12:00:00Z","synthetic":True}
            attrs = {"assessor":{"owner":f"DEMO Owner {index+1}","assessed_value":round(value*.83),"square_feet":1100+index*23,"bedrooms":2+index%4,"bathrooms":1+index%3,"property_type":"single_family"},"recorder":{"owner":f"DEMO Owner {index+1}" if index%6 else f"DEMO Trust {index+1}","debt":round(value*(.2+.05*(index%8))),"sale_price":round(value*.68),"sale_date":"2024-06-12"},"zoning":{"zoning":["R-1","R-2","RM-1"][index%3],"lot_size":5400+index*137},"market":{"estimated_value":value,"purchase_price":round(value*(.58+(index%5)*.025)),"repairs":round(value*(.08+(index%4)*.015)),"holding_costs":5000,"closing_costs":3000,"selling_cost_pct":6}}
            for category in sorted(CATEGORIES):
                records.append(dict(common,source_id="demo-"+category,source_record_id=parcel+"-"+category,category=category,attributes=attrs[category]))
        result = self.ingest(records)
        result.update(synthetic=True,demo_properties=40,demo_records=160)
        return result

    def export_csv(self):
        stream = io.StringIO(newline="")
        fields = ["id","parcel_id","address","state","county_fips","owner","assessed_value","estimated_value","debt","zoning","risk_score","score","updated_at","synthetic"]
        writer = csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        with self.lock:
            for row in self.db.execute("SELECT * FROM properties ORDER BY updated_at DESC,id"):
                item = self.property_item(row)
                # Neutralize spreadsheet formulas from untrusted government/vendor text.
                writer.writerow({k:("'"+v if isinstance(v,str) and v[:1] in {"=","+","-","@","\t","\r"} else v) for k,v in item.items() if k in fields})
        return stream.getvalue()


def handler_for(store, web_root=None):
    root = Path(web_root or Path(__file__).resolve().parents[2]/"web").resolve()
    key = os.environ.get("BRAIN_API_KEY", "")
    intelligence = IntelligenceGateway()
    brain = UnderwritingGateway(store)

    class Handler(BaseHTTPRequestHandler):
        server_version = "101XVC-BRAIN/1.0"

        def log_message(self, fmt, *args):
            # Do not log auth headers or full query strings.
            print("%s %s" % (self.address_string(), fmt % args), flush=True)

        def send_json(self, data, status=200):
            raw = compact(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            if key:
                import hmac
                return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer "+key)
            # No-key development mode is local-only, even if explicitly bound widely.
            allowed_hosts = {"localhost", "127.0.0.1", "::1"}
            if urllib.parse.urlsplit("//"+self.headers.get("Host", "")).hostname not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed_origin = urllib.parse.urlsplit(origin)
                if parsed_origin.hostname not in allowed_hosts or parsed_origin.netloc != self.headers.get("Host", ""):
                    return False
            try:
                return ipaddress.ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ValueError("Content-Length must be an integer") from None
            if not 0 < length <= MAX_BODY:
                raise ValueError("JSON body must be between 1 byte and 16 MiB")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError("JSON body must be an object")
            return data

        def dispatch(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = {k:v[-1] for k,v in urllib.parse.parse_qs(parsed.query).items()}
            if not path.startswith("/api/"):
                if self.command != "GET":
                    self.send_json({"error":"not found"},404)
                    return
                relative = path.lstrip("/") or "index.html"
                candidate = (root/relative).resolve()
                if not candidate.is_relative_to(root) or not candidate.is_file():
                    self.send_json({"error":"not found"},404)
                    return
                raw = candidate.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type",mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
                self.send_header("Content-Length",str(len(raw)))
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'; connect-src 'self'")
                self.end_headers()
                self.wfile.write(raw)
                return
            if path != "/api/health" and not self.authorized():
                self.send_json({"error":"Bearer authentication required; without BRAIN_API_KEY only loopback clients can access the API"},401)
                return
            if self.command == "GET":
                if path == "/api/health":
                    self.send_json({"status":"ok","services":{"api":"running","database":"connected","collector":"configured" if os.environ.get("COLLECTOR_URL") else "optional","resolver":"configured" if os.environ.get("RESOLVER_URL") else "python_fallback"},"brand":"101XVC BRAIN","auth_required":bool(key)})
                elif path == "/api/stats": self.send_json(store.stats())
                elif path == "/api/properties": self.send_json(store.properties(q=query.get("q",""),state=query.get("state",""),category=query.get("category",""),limit=query.get("limit",100),offset=query.get("offset",0)))
                elif path.startswith("/api/properties/"):
                    data = store.detail(path[len("/api/properties/"):])
                    self.send_json(data or {"error":"property not found"},200 if data else 404)
                elif path == "/api/sources": self.send_json(store.sources())
                elif path == "/api/scout": self.send_json(store.scout(query.get("state",""),query.get("min_profit",20000),query.get("limit",500)))
                elif path == "/api/watchlist": self.send_json(store.watchlist())
                elif path == "/api/activity": self.send_json(store.activities())
                elif path == "/api/jobs": self.send_json(store.jobs())
                elif path == "/api/knowledge": self.send_json(intelligence.request("/search",{"query":query.get("q",""),"limit":int(query.get("limit",10))}))
                elif path == "/api/models": self.send_json(intelligence.request("/models"))
                elif path == "/api/documents": self.send_json(brain.document_store().list(query.get("property_id")))
                elif path.startswith("/api/documents/"):
                    document=brain.document_store().get(path[len("/api/documents/"):])
                    self.send_json(document or {"error":"document not found"},200 if document else 404)
                elif path == "/api/brain/episodes": self.send_json(brain.initialize().ledger.episodes(query.get("property_id")))
                elif path.startswith("/api/brain/episodes/"):
                    detail=brain.initialize().ledger.get_episode(path[len("/api/brain/episodes/"):])
                    self.send_json(detail or {"error":"episode not found"},200 if detail else 404)
                elif path == "/api/brain/rules": self.send_json(brain.initialize().ledger.rules(query))
                elif path == "/api/brain/portfolio": self.send_json(brain.initialize().engine.portfolio())
                elif path == "/api/brain/queue": self.send_json(brain.initialize().engine.queue())
                elif path == "/api/brain/models": self.send_json(brain.initialize().registry.status())
                elif path.startswith("/api/brain/report/"):
                    detail=store.detail(path[len("/api/brain/report/"):])
                    if detail:self.send_json(brain.initialize().engine.report(detail,query.get("episode_id"),{}))
                    else:self.send_json({"error":"property not found"},404)
                elif path == "/api/export":
                    raw = store.export_csv().encode()
                    self.send_response(200)
                    self.send_header("Content-Type","text/csv; charset=utf-8")
                    self.send_header("Content-Disposition",'attachment; filename="101xvc-brain-properties.csv"')
                    self.send_header("Content-Length",str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                else: self.send_json({"error":"not found"},404)
            elif self.command == "POST":
                data = self.read_json()
                if path == "/api/ingest": self.send_json(store.ingest(store.prepare_records(data)))
                elif path == "/api/sources": self.send_json(store.add_source(data),201)
                elif path == "/api/seed": self.send_json(store.seed())
                elif path == "/api/watchlist": self.send_json(store.add_watch(data.get("property_id")),201)
                elif path == "/api/jobs": self.send_json(store.start_job(data.get("source_id")),202)
                elif path == "/api/predict": self.send_json(intelligence.request("/predict",data))
                elif path == "/api/train": self.send_json(intelligence.request("/train",data))
                elif path == "/api/extract": self.send_json(intelligence.request("/extract",data))
                elif path == "/api/documents":
                    if data.get('property_id') and not store.detail(data['property_id']):raise ValueError('property_id does not exist')
                    if data.get('episode_id'):
                        episode=brain.initialize().ledger.get_episode(data['episode_id'])
                        if not episode:raise ValueError('episode_id does not exist')
                        linked_property=episode['episode']['property_id']
                        if data.get('property_id') and data['property_id']!=linked_property:raise ValueError('Document property link differs from episode property')
                        data['property_id']=linked_property
                    self.send_json(brain.document_store().put(data),201)
                elif path == "/api/brain/episodes": self.send_json({"episode":brain.initialize().ledger.add_episode(data.get('episode',data))},201)
                elif path.startswith("/api/brain/episodes/") and path.endswith("/events"):
                    episode_id=path[len('/api/brain/episodes/'):-len('/events')]
                    self.send_json({"event":brain.initialize().ledger.add_event(episode_id,data)},201)
                elif path.startswith("/api/brain/episodes/") and path.endswith("/decisions"):
                    episode_id=path[len('/api/brain/episodes/'):-len('/decisions')]
                    self.send_json({"decision":brain.initialize().ledger.record_decision(episode_id,data)},201)
                elif path == "/api/brain/rules": self.send_json({"rule":brain.initialize().ledger.add_rule(data.get('rule',data))},201)
                elif path == "/api/brain/models/train":
                    service=brain.initialize()
                    rows=data.get('rows')
                    if rows is None:rows=service.ledger.model_rows(data.get('kind'),data.get('as_of'))
                    self.send_json(service.registry.train(data.get('kind'),rows,synthetic=data.get('synthetic',False)))
                elif path == "/api/brain/models/promote": self.send_json(brain.initialize().registry.promote(data.get('model_id')))
                elif path == "/api/brain/models/rollback": self.send_json(brain.initialize().registry.rollback(data.get('kind'),data.get('model_id')))
                elif path.startswith("/api/brain/report/"):
                    detail=store.detail(path[len("/api/brain/report/"):])
                    if detail:self.send_json(brain.initialize().engine.report(detail,data.get('episode_id',query.get('episode_id')),data.get('scenario',data)))
                    else:self.send_json({"error":"property not found"},404)
                elif path == "/api/underwrite":
                    if data.get("property_id"):
                        detail = store.detail(data["property_id"])
                        if not detail:
                            self.send_json({"error":"property not found"},404)
                            return
                        data = dict(detail["underwriting"],**data)
                    self.send_json(underwrite(data))
                else: self.send_json({"error":"not found"},404)
            elif self.command == "DELETE" and path.startswith("/api/watchlist/"):
                self.send_json(store.delete_watch(path[len("/api/watchlist/"):]))
            elif self.command == "DELETE" and path.startswith("/api/sources/"):
                self.send_json(store.delete_source(path[len("/api/sources/"):]))
            elif self.command == "PUT" and path.startswith("/api/sources/"):
                self.send_json(store.update_source(path[len("/api/sources/"):],self.read_json()))
            else:
                self.send_json({"error":"not found"},404)

        def safe_dispatch(self):
            try:
                self.dispatch()
            except (ValueError,TypeError,json.JSONDecodeError) as exc:
                self.send_json({"error":str(exc)},400)
            except (BrokenPipeError,ConnectionResetError):
                pass
            except OSError:
                self.send_json({"error":"Configured local service is unavailable; start the project launcher or check service URLs"},503)
            except Exception:
                self.send_json({"error":"internal server error"},500)
                import traceback
                traceback.print_exc()

        do_GET = safe_dispatch
        do_POST = safe_dispatch
        do_DELETE = safe_dispatch
        do_PUT = safe_dispatch
    return Handler


def main():
    parser = argparse.ArgumentParser(description="101XVC BRAIN property intelligence API")
    parser.add_argument("--host",default=os.environ.get("BRAIN_HOST","127.0.0.1"))
    parser.add_argument("--port",type=int,default=int(os.environ.get("BRAIN_PORT","8080")))
    parser.add_argument("--db",default=os.environ.get("BRAIN_DB","data/brain.sqlite3"))
    parser.add_argument("--seed",action="store_true",help="load explicitly synthetic demo observations")
    args = parser.parse_args()
    store = BrainStore(args.db)
    if args.seed:
        print(compact(store.seed()))
    server = ThreadingHTTPServer((args.host,args.port),handler_for(store))
    print(f"101XVC BRAIN listening on http://{args.host}:{args.port}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
