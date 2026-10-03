import sys
import importlib.util
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services'/'intelligence'))
from engine import KnowledgeIndex,OpportunityModel,extract

class IntelligenceTests(unittest.TestCase):
    def test_search_uses_local_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'Debt.md').write_text('# Debt\nDebt service coverage ratio measures cash flow against debt payments.')
            Path(folder,'Title.md').write_text('# Title\nParcel title recording and liens.')
            result=KnowledgeIndex(folder).search('debt service coverage')
            self.assertEqual(result['results'][0]['title'],'Debt')
            self.assertEqual(KnowledgeIndex(folder).search('xyzabsent')['results'],[])

    def test_actual_model_training_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder,'model.json')
            model=OpportunityModel(path)
            result=model.train_reference()
            self.assertTrue(result['synthetic'])
            good=model.predict({'equity_pct':0.9,'discount_pct':0.5,'ltv':0.1})
            bad=model.predict({'equity_pct':0.1,'discount_pct':-0.2,'ltv':0.9,'repair_ratio':0.5})
            self.assertGreater(good['probability'],bad['probability'])
            self.assertEqual(OpportunityModel(path).predict({'equity_pct':0.9,'discount_pct':0.5,'ltv':0.1}),good)
            with self.assertRaises(ValueError): model.predict({'ltv':float('nan')})

    def test_extraction_review_flag(self):
        result=extract('APN: 000-123. Zoning: R-2. Sold $550,000 on 2025-01-02')
        self.assertTrue(result['review_required'])
        self.assertIn('$550,000',result['entities']['money'])

    def test_training_rejects_ambiguous_holdout_labels_and_bad_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            model=OpportunityModel(Path(folder,'model.json'))
            rows=[{'features':{'equity_pct':index/20},'label':index%2} for index in range(20)]
            for invalid in ('not rows',[None]*20,[{'features':[],'label':0}]*20):
                with self.assertRaises(ValueError):model.train(invalid)
            with self.assertRaises(ValueError):model.train(rows,synthetic='false')
            contradictory=rows+[{'features':rows[0]['features'],'label':1}]
            with self.assertRaisesRegex(ValueError,'conflicting labels'):model.train(contradictory)
            self.assertFalse(model.path.exists())

    def test_synthetic_row_provenance_marks_entire_training_run(self):
        with tempfile.TemporaryDirectory() as folder:
            model=OpportunityModel(Path(folder,'model.json'))
            rows=[{'features':{'equity_pct':index/20},'label':index%2} for index in range(20)]
            rows[0]['synthetic']=True
            result=model.train(rows,synthetic=False)
            self.assertTrue(result['synthetic'])
            self.assertTrue(model.predict({'equity_pct':.5})['synthetic'])

    def test_http_rejects_array_body_and_no_key_remote_client(self):
        path=Path(__file__).resolve().parents[1]/'services/intelligence/server.py'
        spec=importlib.util.spec_from_file_location('brain_intelligence_test_server',path)
        service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
        with patch.dict(os.environ,{'BRAIN_API_KEY':''}):
            remote=service.Handler.__new__(service.Handler)
            remote.client_address=('192.0.2.1',55000);remote.headers={}
            self.assertFalse(remote.authorized())
            remote.client_address=('127.0.0.1',55000)
            self.assertTrue(remote.authorized())
            server=ThreadingHTTPServer(('127.0.0.1',0),service.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                req=urllib.request.Request('http://127.0.0.1:'+str(server.server_address[1])+'/train',data=b'[]',headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(req)
                self.assertEqual(result.exception.code,400)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__': unittest.main()
