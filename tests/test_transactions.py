"""Permanent episodes, decision snapshots, settlement integrity and no future leakage."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from services.underwriting.ledger import TransactionLedger

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('transaction_api',ROOT/'services/api/app.py')
api=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(api)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=api.BrainStore(Path(self.tmp.name)/'brain.sqlite3')
        self.store.add_source({'id':'test-assessor','name':'Test assessor','category':'assessor','state':'TX','county_fips':'48439'})
        self.store.ingest([{'source_id':'test-assessor','source_record_id':'1','parcel_id':'00012','state':'TX','county_fips':'48439','address':'12 Sample St','category':'assessor','observed_at':'2026-07-01T12:00:00Z','attributes':{'assessed_value':200000}}])
        self.ledger=TransactionLedger(self.store.db,self.store.lock)
        self.episode=self.ledger.add_episode({'id':'episode-test','property_id':'48439-00012','intake_date':'2026-07-15','asking_price':150000,'target_price':130000,'partner_id':'partner-one','stage':'intake'})

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def event(self,kind,data,observed='2026-08-10T12:00:00Z',available=None,event_id=None):
        body={'kind':kind,'data':data,'observed_at':observed,'available_at':available or observed}
        if event_id:body['id']=event_id
        return self.ledger.add_event(self.episode['id'],body)

    def decision(self,**updates):
        body={'id':'decision-test','decision_at':'2026-08-01T12:00:00Z','prediction':{'closing_probability':None},'recommendation':{'action':'inspect'},'evidence_snapshot':{'features':{'estimated_value':200000,'target_price':130000,'offered_price':130000,'state':'TX'},'observed_at':'2026-07-01T12:00:00Z','available_at':'2026-07-02T12:00:00Z'},'model_versions':{}}
        body.update(updates)
        return self.ledger.record_decision(self.episode['id'],body)

    def settlement(self,**updates):
        data={'closed_at':'2026-08-30T12:00:00Z','gross_spread':30000,'partner_share':15000,'company_receipts':15000,'cash_received':15000,'cash_received_at':'2026-09-05T12:00:00Z','acquisition_costs':2000,'transaction_costs':1000,'meta':{'as_is_value':170000,'actual_repairs':25000}}
        data.update(updates)
        return self.event('settlement',data,'2026-09-10T12:00:00Z',event_id=updates.pop('id',None) if 'id' in updates else None)

    def test_episode_event_and_decision_persist_and_are_sql_immutable(self):
        note=self.event('note',{'text':'Original owner document requested'})
        decision=self.decision()
        self.event('update',{'changes':{'target_price':125000,'stage':'offered'},'reason':'Recorded seller counter'})
        detail=self.ledger.get_episode(self.episode['id'])
        self.assertEqual(detail['episode']['target_price'],125000)
        self.assertEqual(detail['events'][-1]['prior_state']['target_price'],130000)
        self.assertEqual(detail['decisions'][0]['evidence_snapshot']['features']['target_price'],130000)
        for table,key in [('brain_events',note['id']),('brain_decisions',decision['id']),('brain_episodes',self.episode['id'])]:
            with self.assertRaises(sqlite3.IntegrityError):self.store.db.execute('DELETE FROM '+table+' WHERE id=?',(key,))
            self.store.db.rollback()
        self.store.close();self.store=api.BrainStore(Path(self.tmp.name)/'brain.sqlite3');self.ledger=TransactionLedger(self.store.db,self.store.lock)
        self.assertEqual(self.ledger.get_episode(self.episode['id'])['episode']['target_price'],125000)
        self.assertEqual(len(self.ledger.get_episode(self.episode['id'])['decisions']),1)

    def test_stable_event_identity_is_idempotent_and_cannot_rewrite(self):
        request={'id':'event-one','kind':'offer','observed_at':'2026-08-10T12:00:00Z','available_at':'2026-08-10T12:00:00Z','data':{'price':130000,'response':'pending'}}
        first=self.ledger.add_event(self.episode['id'],request)
        second=self.ledger.add_event(self.episode['id'],request)
        self.assertEqual(first['recorded_at'],second['recorded_at'])
        self.assertEqual(len(self.ledger.get_episode(self.episode['id'])['offers']),1)
        altered={**request,'data':{'price':140000,'response':'pending'}}
        with self.assertRaises(ValueError):self.ledger.add_event(self.episode['id'],altered)

    def test_settlement_split_cash_and_closed_outcome_integrity(self):
        with self.assertRaisesRegex(ValueError,'settlement'):self.event('outcome',{'status':'closed','occurred_at':'2026-08-30'})
        with self.assertRaisesRegex(ValueError,'gross_spread'):self.settlement(company_receipts=14000)
        with self.assertRaisesRegex(ValueError,'cash_received'):self.settlement(cash_received=None)
        settlement=self.settlement()
        outcome=self.event('outcome',{'status':'closed','occurred_at':'2026-08-30T12:00:00Z'},'2026-09-10T12:00:00Z')
        self.assertEqual(self.ledger.get_episode(self.episode['id'])['episode']['stage'],'closed')
        self.assertEqual(settlement['retained_fee'],15000)
        self.assertEqual(settlement['collected_cash'],15000)
        self.assertEqual(self.settlement()['id'],settlement['id'])
        with self.assertRaisesRegex(ValueError,'supersede'):self.settlement(cash_received=14000)
        correction=self.settlement(cash_received=14000,supersedes_event_id=settlement['id'])
        self.assertEqual(self.ledger.get_episode(self.episode['id'])['current_settlement']['id'],correction['id'])
        self.assertEqual(len(self.ledger.get_episode(self.episode['id'])['settlements']),2)

    def test_training_uses_original_snapshot_and_censors_unfinished_contract(self):
        self.decision()
        self.event('offer',{'price':130000,'response':'accepted'})
        self.settlement()
        self.event('outcome',{'status':'closed','occurred_at':'2026-08-30T12:00:00Z'},'2026-09-10T12:00:00Z')
        early=self.ledger.model_rows('closing','2026-08-20T12:00:00Z')
        self.assertEqual(early[0]['label'],{'duration':19,'event':'censored'})
        later=self.ledger.model_rows('closing','2026-09-15T12:00:00Z')
        self.assertEqual(later[0]['label'],{'duration':29,'event':'closed'})
        self.assertEqual(self.ledger.model_rows('cash','2026-09-01'),[])
        cash=self.ledger.model_rows('cash','2026-09-15')[0]
        self.assertEqual(cash['label'],6)
        self.assertEqual(self.ledger.model_rows('valuation','2026-09-15')[0]['label'],170000)
        self.assertEqual(self.ledger.model_rows('repairs','2026-09-15')[0]['label'],25000)
        self.assertEqual(self.ledger.model_rows('acceptance','2026-09-15')[0]['label'],1)
        with self.store.db:self.store.db.execute("UPDATE properties SET data=? WHERE id=?",(json.dumps({'estimated_value':900000}),'48439-00012'))
        self.assertEqual(self.ledger.model_rows('closing','2026-09-15')[0]['features']['estimated_value'],200000)

    def test_future_snapshot_and_mutated_decision_rejected(self):
        with self.assertRaisesRegex(ValueError,'unavailable'):self.decision(evidence_snapshot={'features':{'value':100},'available_at':'2026-08-02'})
        first=self.decision();again=self.decision()
        self.assertEqual(first['recorded_at'],again['recorded_at'])
        with self.assertRaisesRegex(ValueError,'immutable'):self.decision(recommendation={'action':'pay'})

    def test_acceptance_at_another_price_is_not_a_counterfactual_label(self):
        self.decision()
        self.event('offer',{'price':140000,'response':'accepted'})
        self.assertEqual(self.ledger.model_rows('acceptance','2026-09-15'),[])
        self.event('offer',{'price':130000,'response':'rejected','synthetic':True},observed='2026-08-12T12:00:00Z')
        rows=self.ledger.model_rows('acceptance','2026-09-15')
        self.assertEqual(rows[0]['label'],0)
        self.assertTrue(rows[0]['synthetic'])

    def test_unfinished_repairs_are_not_a_complete_cost_target(self):
        self.decision()
        self.event('expense',{'amount':2000,'type':'repairs','paid':True})
        self.assertEqual(self.ledger.model_rows('repairs','2026-09-15'),[])
        self.event('milestone',{'name':'repairs_complete','status':'completed','verified':True},observed='2026-08-11T12:00:00Z')
        self.assertEqual(self.ledger.model_rows('repairs','2026-09-15')[0]['label'],2000)

    def test_rule_versions_require_review_and_preserve_history(self):
        draft={'id':'rule-test','jurisdiction':'state','state':'TX','effective_from':'2026-08-01','status':'draft','rules':{'min_profit':20000,'partner_split_pct':50,'required_documents':['ownership evidence']}}
        self.ledger.add_rule(draft)
        with self.assertRaisesRegex(ValueError,'approved_by'):self.ledger.add_rule({**draft,'id':'reviewed','status':'reviewed'})
        reviewed=self.ledger.add_rule({**draft,'id':'reviewed','status':'reviewed','approved_by':'Authorized reviewer'})
        self.assertEqual(reviewed['rules']['min_profit'],20000)
        self.assertEqual(len(self.ledger.rules({'state':'TX','as_of':'2026-08-02'})['items']),2)
        self.assertEqual(self.ledger.rules({'as_of':'2026-07-01'})['items'],[])
        with self.assertRaisesRegex(ValueError,'immutable'):self.ledger.add_rule({**draft,'rules':{'min_profit':1}})

    def test_invalid_event_fields_rejected_without_ledger_changes(self):
        examples=[('offer',{'price':-1}),('bid',{'price':100,'status':'guaranteed'}),('expense',{'amount':float('nan'),'type':'marketing'}),('milestone',{'name':'title','verified':'yes'}),('update',{'changes':{'property_id':'wrong'},'reason':'bad'}),('outcome',{'status':'cancelled'})]
        for kind,data in examples:
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):self.event(kind,data)
        self.assertEqual(self.ledger.get_episode(self.episode['id'])['events'],[])


if __name__=='__main__':unittest.main()
