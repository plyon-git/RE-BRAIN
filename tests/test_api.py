"""Exercise actual SQLite persistence, provenance, identity and HTTP authorization."""
import importlib.util
import csv
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("brain_api", ROOT / "services" / "api" / "app.py")
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class BrainStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "brain.sqlite3"
        self.store = api.BrainStore(self.path)
        for category in ("assessor","recorder","zoning","market"):
            self.store.add_source({"id":category,"name":category,"category":category,"state":"TX","county_fips":"48439","adapter":"manual"})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def record(self, category="assessor", **updates):
        record = {"source_id":category,"source_record_id":"000012-"+category,"parcel_id":"00-0012","county_fips":"48439","state":"TX","address":"10 Sample St, Fort Worth, TX","category":category,"observed_at":"2026-09-01T12:00:00Z","attributes":{"owner":"Alice","assessed_value":200000}}
        record.update(updates)
        return record

    def test_persistent_cross_category_merge_and_field_provenance(self):
        assessor = self.record()
        recorder = self.record("recorder",observed_at="2026-08-01T12:00:00Z",attributes={"owner":"Recorded Trust","debt":75000})
        market = self.record("market",attributes={"estimated_value":300000})
        zoning = self.record("zoning",attributes={"zoning":"R-1"})
        result = self.store.ingest([assessor,recorder,market,zoning])
        self.assertEqual(result["accepted"],4)
        self.assertEqual(result["properties"],1)
        identifier = "48439-000012"
        detail = self.store.detail(identifier)
        self.assertEqual(detail["property"]["parcel_id"],"000012")
        self.assertEqual(detail["property"]["owner"],"Recorded Trust")
        self.assertEqual(detail["field_provenance"]["owner"]["source_id"],"recorder")
        self.assertEqual(detail["field_provenance"]["estimated_value"]["source_record_id"],"000012-market")
        self.assertEqual(detail["conflicts"][0]["field"],"owner")
        self.assertEqual(len(detail["evidence"]),4)
        self.assertFalse(detail["property"]["synthetic"])
        self.store.close()
        self.store = api.BrainStore(self.path)
        restored = self.store.detail(identifier)
        self.assertEqual(restored["property"]["owner"],"Recorded Trust")
        self.assertEqual(len(restored["evidence"]),4)

    def test_idempotence_and_newer_authoritative_observation(self):
        first = self.record()
        self.store.ingest([first,first])
        self.assertEqual(self.store.stats()["evidence"],1)
        second = self.record(source_record_id="second",observed_at="2026-09-02T12:00:00Z",attributes={"owner":"Bob","assessed_value":220000})
        self.store.ingest([second])
        self.assertEqual(self.store.detail("48439-000012")["property"]["owner"],"Bob")
        self.assertEqual(self.store.stats()["evidence"],2)

    def test_source_versions_preserve_receipt_times_and_do_not_rewind_current_facts(self):
        old=self.record(attributes={'owner':'Alice','assessed_value':200000})
        self.store.ingest([old]);original=self.store.detail('48439-000012')['evidence'][0]
        newer=self.record(observed_at='2026-09-03T12:00:00Z',attributes={'owner':'Bob','assessed_value':210000})
        self.store.ingest([newer,old])
        detail=self.store.detail('48439-000012')
        self.assertEqual(detail['property']['owner'],'Bob')
        self.assertEqual(len(detail['evidence_history']),2)
        self.assertEqual(detail['evidence_history'][0]['recorded_at'],original['recorded_at'])
        self.assertEqual(detail['field_provenance']['owner']['availability_basis'],'first_ingestion_receipt')

    def test_validation_rejects_unsafe_or_identity_losing_fields(self):
        for changes in ({"parcel_id":12},{"state":"ZZ"},{"county_fips":"439"},{"source_id":"unknown"},{"category":"tax"},{"observed_at":"tomorrow"},{"attributes":{"estimated_value":float("nan")}}):
            with self.subTest(changes=changes):
                result = self.store.ingest([self.record(**changes)])
                self.assertEqual(result["rejected"],1)
                self.assertEqual(result["accepted"],0)
        self.assertEqual(self.store.stats()["properties"],0)

    def test_same_source_record_cannot_move_to_another_parcel(self):
        self.store.ingest([self.record()])
        result = self.store.ingest([self.record(parcel_id="different-parcel")])
        self.assertEqual(result["rejected"],1)
        self.assertEqual(self.store.stats()["properties"],1)

    def test_address_fallback_is_county_scoped_and_parcels_do_not_false_merge(self):
        self.store.ingest([self.record(parcel_id=None,source_record_id="address-only")])
        identity = api.resolve_record(self.record(parcel_id=None))
        self.assertIn("48439-ADDR-",identity["property_id"])
        self.assertTrue(self.store.detail(identity["property_id"]))
        self.store.ingest([self.record(parcel_id="0012",source_record_id="parcel-one"),self.record(parcel_id="12",source_record_id="parcel-two")])
        self.assertEqual(self.store.stats()["properties"],3)
        self.assertNotEqual(api.resolve_record(self.record(parcel_id="0012"))["property_id"],api.resolve_record(self.record(parcel_id="12"))["property_id"])

    def test_watchlist_and_property_filters(self):
        self.store.ingest([self.record()])
        self.store.add_watch("48439-000012")
        self.store.add_watch("48439-000012")
        self.assertEqual(len(self.store.watchlist()["items"]),1)
        self.assertEqual(self.store.properties(q="Sample",state="TX",category="assessor")["total"],1)
        self.assertEqual(self.store.properties(state="AZ")["total"],0)
        self.assertEqual(self.store.properties(q="%")["total"],0)
        self.assertTrue(self.store.delete_watch("48439-000012")["deleted"])
        self.assertFalse(self.store.delete_watch("48439-000012")["deleted"])

    def test_underwriting_math_and_negative_profit(self):
        result = api.underwrite({"arv":300000,"purchase_price":200000,"repairs":35000,"holding_costs":7000,"closing_costs":3000,"selling_cost_pct":6,"partner_split_pct":50,"min_profit":20000})
        self.assertEqual(result["selling_costs"],18000)
        self.assertEqual(result["gross_profit"],37000)
        self.assertEqual(result["company_share"],18500)
        self.assertEqual(result["max_offer"],217000)
        self.assertTrue(result["qualifies"])
        self.assertEqual(api.underwrite({"arv":100,"purchase_price":200,"selling_cost_pct":0})["gross_profit"],-100)
        for invalid in ({"arv":-1},{"partner_split_pct":101},{"repairs":"not money"},{"selling_cost_pct":float("inf")}):
            with self.assertRaises(ValueError): api.underwrite(invalid)

    def test_synthetic_seed_has_overlap_and_is_idempotent(self):
        self.store.seed()
        first = self.store.stats()
        self.store.seed()
        second = self.store.stats()
        self.assertEqual(first["properties"],40)
        self.assertEqual(first["evidence"],160)
        self.assertEqual(first["properties"],second["properties"])
        self.assertEqual(first["evidence"],second["evidence"])
        self.assertEqual(first["synthetic_properties"],40)
        self.assertGreater(first["conflicts"],0)
        scouts = self.store.scout()["items"]
        self.assertTrue(scouts)
        self.assertTrue(all(item["synthetic"] and item["provenance"] for item in scouts))

    def test_source_options_mapping_and_invalid_changes(self):
        source = self.store.add_source({"id":"csv-source","name":"User CSV","category":"assessor","state":"TX","county_fips":"48439","url":"https://example.org/properties.csv","adapter":"csv","mapping":{"parcel_id":"APN"},"options":{"delimiter":","}})
        self.assertEqual(source["mapping"]["parcel_id"],"APN")
        self.store.ingest([self.record()])
        with self.assertRaises(ValueError): self.store.add_source({"id":"assessor","name":"Changed","category":"market","state":"TX","county_fips":"48439"})

    def test_envelope_defaults_keep_csv_import_provenance(self):
        payload = {"source_id":"assessor","synthetic":True,"records":[{"parcel_id":"00-0099","address":"99 CSV Avenue","owner":"Demo CSV Owner","assessed_value":"234500","_raw_record":{"APN":"00-0099","OWNER":"Demo CSV Owner","VALUE":"234500"}}]}
        prepared = self.store.prepare_records(payload)
        self.assertEqual(prepared[0]["county_fips"],"48439")
        self.assertEqual(prepared[0]["category"],"assessor")
        self.assertTrue(prepared[0]["source_record_id"].startswith("row-"))
        first = self.store.ingest(prepared)
        self.store.ingest(self.store.prepare_records(payload))
        self.assertEqual(first["accepted"],1)
        self.assertEqual(self.store.stats()["evidence"],1)
        detail = self.store.detail("48439-000099")
        self.assertTrue(detail["property"]["synthetic"])
        self.assertEqual(detail["property"]["assessed_value"],234500)
        self.assertEqual(detail["evidence"][0]["_raw_record"]["APN"],"00-0099")
        self.store.update_source("assessor",{"name":"Updated assessor"})
        with self.assertRaises(ValueError): self.store.delete_source("assessor")
        self.assertTrue(self.store.delete_source("zoning")["deleted"])

    def test_export_neutralizes_formula_text(self):
        self.store.ingest([self.record(attributes={"owner":"=HYPERLINK(\"x\")"})])
        exported = self.store.export_csv()
        self.assertIn("'=HYPERLINK",exported)

    def test_export_and_scout_include_properties_beyond_ten_thousand(self):
        rows = []
        for index in range(10005):
            data = {"estimated_value":250000,"purchase_price":150000,"repairs":20000,"holding_costs":5000,"closing_costs":3000,"selling_cost_pct":6,"score":99 if index==10004 else 10,"field_provenance":{},"conflicts":[],"synthetic":True}
            rows.append((f"48439-{index:08d}",f"{index:08d}",f"{index} Export Demo Street","TX","48439",api.compact(data),"2026-09-01T12:00:00Z",1))
        with self.store.db:
            self.store.db.executemany("INSERT INTO properties VALUES(?,?,?,?,?,?,?,?)",rows)
        exported = list(csv.DictReader(io.StringIO(self.store.export_csv())))
        self.assertEqual(len(exported),10005)
        self.assertIn("48439-00010004",{row["id"] for row in exported})
        selected = self.store.scout(limit=1)
        self.assertEqual(selected["total_matches"],10005)
        self.assertEqual(selected["items"][0]["id"],"48439-00010004")
        self.assertTrue(selected["truncated"])
        self.assertEqual(self.store.stats()["properties"],10005)

    def test_ssrf_rejects_private_and_credential_urls(self):
        for url in ("http://127.0.0.1/file.csv","http://169.254.169.254/latest/meta-data","file:///etc/passwd","https://user:password@example.org/data","http://127.0.0.1:8080/health"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError): api.public_url(url)

    def test_http_contract_and_authentication(self):
        with patch.dict(os.environ,{"BRAIN_API_KEY":"test-key"}):
            server = ThreadingHTTPServer(("127.0.0.1",0),api.handler_for(self.store,ROOT/"web"))
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base = "http://127.0.0.1:"+str(server.server_address[1])
            try:
                with urllib.request.urlopen(base+"/api/health") as response:
                    self.assertEqual(json.load(response)["status"],"ok")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(base+"/api/stats")
                self.assertEqual(raised.exception.code,401)
                request = urllib.request.Request(base+"/api/ingest",data=json.dumps({"records":[self.record()]}).encode(),headers={"Authorization":"Bearer test-key","Content-Type":"application/json"},method="POST")
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(json.load(response)["accepted"],1)
                request = urllib.request.Request(base+"/api/properties/48439-000012",headers={"Authorization":"Bearer test-key"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(json.load(response)["property"]["owner"],"Alice")
                bad = urllib.request.Request(base+"/api/underwrite",data=b'{"arv":-1}',headers={"Authorization":"Bearer test-key"},method="POST")
                with self.assertRaises(urllib.error.HTTPError) as invalid: urllib.request.urlopen(bad)
                self.assertEqual(invalid.exception.code,400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
