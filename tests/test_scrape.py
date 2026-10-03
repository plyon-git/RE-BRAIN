import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scrape import parse_tables

class ScraperTests(unittest.TestCase):
    def test_public_table_preserves_ids_and_nested_text(self):
        tables=parse_tables('<table><tr><th>APN</th><th>Owner</th></tr><tr><td>000-12</td><td><b>Example</b> LLC &amp; Trust</td></tr></table>')
        self.assertEqual(tables,[[['APN','Owner'],['000-12','Example LLC & Trust']]])
    def test_non_table_content_not_collected(self):
        self.assertEqual(parse_tables('<p>Private unrelated text</p>'),[])
    def test_local_fixture_labels_survive_preprocessing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'input.html').write_text('<table><tr><th>APN</th><th>Address</th><th>Value</th></tr><tr><td>000-12</td><td>12 Demo St</td><td>$250,000</td></tr></table>')
            (root/'config.json').write_text(json.dumps({'id':'test-fixture','category':'assessor','county_fips':'48439','state':'TX','synthetic':True,'mapping':{'parcel_id':'APN','address':'Address','assessed_value':'Value'}}))
            script=Path(__file__).resolve().parents[1]/'scripts/scrape.py'
            proc=subprocess.run([sys.executable,str(script),'--html-file',str(root/'input.html'),'--config',str(root/'config.json'),'--output',str(root/'records.jsonl')],capture_output=True,text=True,check=True)
            summary=json.loads(proc.stdout)
            record=json.loads((root/'records.jsonl').read_text())
            self.assertTrue(summary['synthetic'])
            self.assertTrue(record['synthetic'])
            self.assertEqual(record['parcel_id'],'000-12')
            self.assertEqual(record['attributes']['assessed_value'],250000)

if __name__=='__main__':unittest.main()
