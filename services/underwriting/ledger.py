"""Append-only transaction evidence and immutable decision snapshots in SQLite.

Current views are derived from permanent events. Training labels are joined to
the evidence available at an original decision; current property enrichment is
never substituted for that snapshot.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
import threading
import uuid
from datetime import datetime,timezone,timedelta

STATES=set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split())
EVENT_KINDS={'offer','bid','milestone','expense','settlement','note','outcome','update','action'}
TERMINAL={'closed','cancelled','expired'}

def stamp():return datetime.now(timezone.utc).isoformat(timespec='microseconds')
def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def moment(value,name='timestamp'):
    if not isinstance(value,str) or not value.strip():raise ValueError(name+' must be an ISO 8601 string')
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:result=result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except ValueError:raise ValueError(name+' must be an ISO 8601 date or datetime') from None
def iso(value,name='timestamp'):return moment(value,name).isoformat(timespec='microseconds')
def amount(value,name,negative=False):
    if isinstance(value,bool):raise ValueError(name+' must be a number')
    try:value=float(value)
    except (ValueError,TypeError):raise ValueError(name+' must be a number') from None
    if not math.isfinite(value) or (not negative and value<0):raise ValueError(name+' must be finite'+('' if negative else ' and nonnegative'))
    return round(value,2)
def identifier(value,name='id'):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',value):raise ValueError(name+' must be a nonempty stable identifier')
    return value
def text(value,name,maximum=5000):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise ValueError(name+' must be nonempty text of at most '+str(maximum)+' characters')
    return value.strip()
def boolean(value,name):
    if not isinstance(value,bool):raise ValueError(name+' must be a boolean')
    return value
def clean_json(value,name):
    try:return json.loads(encode(value))
    except (ValueError,TypeError):raise ValueError(name+' must be finite JSON data') from None
def contains_synthetic(value):
    if isinstance(value,dict):return value.get('synthetic') is True or any(contains_synthetic(item) for item in value.values())
    if isinstance(value,list):return any(contains_synthetic(item) for item in value)
    return False


class TransactionLedger:
    def __init__(self,db,lock=None):
        self.db=db
        self.lock=lock or threading.RLock()
        with self.lock,self.db:
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS brain_episodes(id TEXT PRIMARY KEY,property_id TEXT NOT NULL REFERENCES properties(id),created_at TEXT NOT NULL,data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS brain_episode_property ON brain_episodes(property_id);
              CREATE TABLE IF NOT EXISTS brain_events(id TEXT PRIMARY KEY,episode_id TEXT NOT NULL REFERENCES brain_episodes(id),kind TEXT NOT NULL,observed_at TEXT NOT NULL,available_at TEXT NOT NULL,recorded_at TEXT NOT NULL,data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS brain_event_episode ON brain_events(episode_id,observed_at,available_at);
              CREATE TABLE IF NOT EXISTS brain_decisions(id TEXT PRIMARY KEY,episode_id TEXT NOT NULL REFERENCES brain_episodes(id),decision_at TEXT NOT NULL,recorded_at TEXT NOT NULL,data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS brain_decision_episode ON brain_decisions(episode_id,decision_at);
              CREATE TABLE IF NOT EXISTS brain_rules(id TEXT PRIMARY KEY,effective_from TEXT NOT NULL,recorded_at TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS brain_events_no_update BEFORE UPDATE ON brain_events BEGIN SELECT RAISE(ABORT,'Transaction events are immutable'); END;
              CREATE TRIGGER IF NOT EXISTS brain_events_no_delete BEFORE DELETE ON brain_events BEGIN SELECT RAISE(ABORT,'Transaction events are permanent'); END;
              CREATE TRIGGER IF NOT EXISTS brain_decisions_no_update BEFORE UPDATE ON brain_decisions BEGIN SELECT RAISE(ABORT,'Decision snapshots are immutable'); END;
              CREATE TRIGGER IF NOT EXISTS brain_decisions_no_delete BEFORE DELETE ON brain_decisions BEGIN SELECT RAISE(ABORT,'Decision snapshots are permanent'); END;
              CREATE TRIGGER IF NOT EXISTS brain_rules_no_update BEFORE UPDATE ON brain_rules BEGIN SELECT RAISE(ABORT,'Rule versions are immutable'); END;
              CREATE TRIGGER IF NOT EXISTS brain_rules_no_delete BEFORE DELETE ON brain_rules BEGIN SELECT RAISE(ABORT,'Rule versions are permanent'); END;
              CREATE TRIGGER IF NOT EXISTS brain_episodes_no_update BEFORE UPDATE ON brain_episodes BEGIN SELECT RAISE(ABORT,'Change episode state through an event'); END;
              CREATE TRIGGER IF NOT EXISTS brain_episodes_no_delete BEFORE DELETE ON brain_episodes BEGIN SELECT RAISE(ABORT,'Transaction episodes are permanent'); END;
            ''')

    def _property(self,property_id):
        row=self.db.execute('SELECT * FROM properties WHERE id=?',(property_id,)).fetchone()
        if row is None:return None
        prop=json.loads(row['data'])
        prop.update(id=row['id'],parcel_id=row['parcel_id'],address=row['address'],state=row['state'],county_fips=row['county_fips'],synthetic=bool(row['synthetic']))
        return prop

    def _episode_fields(self,data,initial=False):
        result=dict(data)
        if 'state' in result and result['state']:
            result['state']=text(result['state'],'state',2).upper()
            if result['state'] not in STATES:raise ValueError('state must be a two-letter US state')
        for field in ('intake_date','contract_date','deadline'):
            if result.get(field):result[field]=iso(result[field],field)
        for field in ('asking_price','target_price'):
            if result.get(field) is not None:result[field]=amount(result[field],field)
        if 'stage' in result:
            result['stage']=text(result['stage'],'stage',100)
            if initial and result['stage'] in TERMINAL:raise ValueError('Create the episode open, then record settlement/outcome evidence')
        if result.get('capacity') is not None:
            result['capacity']=amount(result['capacity'],'capacity')
        if 'meta' in result:
            if not isinstance(result['meta'],dict):raise ValueError('meta must be an object')
            result['meta']=clean_json(result['meta'],'meta')
        for field in ('partner_id','buyer_id'):
            if result.get(field) is not None:result[field]=text(result[field],field,200)
        if 'synthetic' in result:result['synthetic']=boolean(result['synthetic'],'synthetic')
        return clean_json(result,'episode')

    def add_episode(self,data):
        if not isinstance(data,dict):raise ValueError('episode must be an object')
        property_id=identifier(data.get('property_id'),'property_id')
        with self.lock,self.db:
            prop=self._property(property_id)
            if prop is None:raise ValueError('property_id does not exist')
            result=self._episode_fields(data,initial=True)
            episode_id=identifier(result.get('id') or 'episode-'+uuid.uuid4().hex)
            result.update(id=episode_id,property_id=property_id,stage=result.get('stage','intake'),intake_date=result.get('intake_date') or stamp(),state=result.get('state') or prop['state'],meta=result.get('meta',{}),synthetic=bool(result.get('synthetic',False) or prop['synthetic']))
            existing=self.db.execute('SELECT data FROM brain_episodes WHERE id=?',(episode_id,)).fetchone()
            if existing:
                prior=json.loads(existing['data'])
                compare=dict(result)
                if 'intake_date' not in data:compare['intake_date']=prior['intake_date']
                if compare!=prior:raise ValueError('episode id already exists with different immutable contents')
                return self.get_episode(episode_id)['episode']
            self.db.execute('INSERT INTO brain_episodes VALUES(?,?,?,?)',(episode_id,property_id,stamp(),encode(result)))
            return self.get_episode(episode_id)['episode']

    @staticmethod
    def event_item(row):
        payload=json.loads(row['data'])
        return dict(payload,id=row['id'],event_id=row['id'],episode_id=row['episode_id'],kind=row['kind'],observed_at=row['observed_at'],available_at=row['available_at'],recorded_at=row['recorded_at'],data=payload)

    @staticmethod
    def decision_item(row):
        return dict(json.loads(row['data']),id=row['id'],decision_id=row['id'],episode_id=row['episode_id'],decision_at=row['decision_at'],recorded_at=row['recorded_at'])

    def get_episode(self,episode_id,as_of=None):
        with self.lock:
            row=self.db.execute('SELECT * FROM brain_episodes WHERE id=?',(episode_id,)).fetchone()
            if row is None:return None
            ep=json.loads(row['data']);ep['created_at']=row['created_at']
            cutoff=iso(as_of,'as_of') if as_of else None
            events=[self.event_item(event) for event in self.db.execute('SELECT * FROM brain_events WHERE episode_id=? ORDER BY observed_at,available_at,recorded_at,id',(episode_id,)) if not cutoff or event['available_at']<=cutoff]
            for event in events:
                if event['kind']=='update':ep.update(event['changes'])
                elif event['kind']=='outcome':ep.update(stage=event['status'],outcome=event['status'],outcome_at=event['occurred_at'])
            prop=self._property(ep['property_id'])
            ep.update(status=ep['stage'],partner=ep.get('partner_id'),contract_price=ep.get('target_price'),capacity_required=ep.get('capacity'),cash_required=ep.get('meta',{}).get('cash_required'),property_snapshot=prop)
            detail={'episode':ep,'events':events,'property':prop}
            for singular,plural in [('offer','offers'),('bid','bids'),('milestone','milestones'),('expense','expenses'),('settlement','settlements')]:detail[plural]=[event for event in events if event['kind']==singular]
            detail['decisions']=[self.decision_item(decision) for decision in self.db.execute('SELECT * FROM brain_decisions WHERE episode_id=? ORDER BY decision_at,id',(episode_id,)) if not cutoff or decision['decision_at']<=cutoff]
            settlements=detail['settlements']
            superseded={event.get('supersedes_event_id') for event in settlements}
            active=[event for event in settlements if event['id'] not in superseded]
            detail['current_settlement']=active[-1] if active else None
            return detail

    def episodes(self,property_id=None):
        with self.lock:
            rows=self.db.execute('SELECT id FROM brain_episodes'+(' WHERE property_id=?' if property_id else '')+' ORDER BY created_at DESC,id',(property_id,) if property_id else ())
            return {'items':[self.get_episode(row['id'])['episode'] for row in rows]}

    def _payload(self,kind,payload,detail):
        result=clean_json(payload,'event data')
        if not isinstance(result,dict):raise ValueError('event data must be an object')
        if kind in {'offer','bid'}:
            result['price']=amount(result.get('price',result.get('amount')),'price')
            result['amount']=result['price']
        if kind=='offer':
            result['response']=result.get('response',result.get('status','pending'))
            if result['response'] not in {'accepted','rejected','counter','pending'}:raise ValueError('offer response must be accepted, rejected, counter or pending')
            result['status']=result['response']
            result.setdefault('terms',{})
        elif kind=='bid':
            result['status']=result.get('status','interest')
            if result['status'] not in {'interest','executable','accepted','funded','withdrawn','rejected','expired'}:raise ValueError('unsupported bid status')
            result['executable']=result['status'] in {'executable','accepted','funded'}
            result.setdefault('conditions',[])
            if result.get('expires_at'):result['expires_at']=iso(result['expires_at'],'expires_at')
        elif kind=='milestone':
            result['name']=text(result.get('name'),'name',200)
            result['status']=result.get('status','pending')
            if result['status'] not in {'pending','in_progress','completed','cleared','blocked','failed','waived','missing'}:raise ValueError('unsupported milestone status')
            if result.get('due_at') and not result.get('due_date'):result['due_date']=result['due_at']
            for field in ('due_date','completed_at'):
                if result.get(field):result[field]=iso(result[field],field)
            for field in ('required','verified'):
                if field in result:result[field]=boolean(result[field],field)
        elif kind=='expense':
            result['amount']=amount(result.get('amount'),'amount')
            result['type']=text(result.get('type',result.get('category')),'expense type',100)
            result['category']=result['type']
            if result.get('paid_at'):result['paid_at']=iso(result['paid_at'],'paid_at')
            result['paid']=boolean(result.get('paid',bool(result.get('paid_at'))),'paid')
            result['status']='paid' if result['paid'] else 'accrued'
        elif kind=='settlement':
            result['closed_at']=iso(result.get('closed_at',result.get('funded_at')),'closed_at')
            result['funded_at']=result['closed_at']
            if 'company_receipts' not in result and 'retained_fee' in result:result['company_receipts']=result['retained_fee']
            if 'cash_received' not in result and 'collected_cash' in result:result['cash_received']=result['collected_cash']
            for field in ('gross_spread','partner_share','company_receipts','acquisition_costs','transaction_costs'):
                result[field]=amount(result.get(field),field)
            if abs(result['gross_spread']-result['partner_share']-result['company_receipts'])>.02:raise ValueError('gross_spread must equal partner_share plus company_receipts; purchase/sale value is not profit')
            result['retained_fee']=result['company_receipts']
            result['cash_received_at']=iso(result['cash_received_at'],'cash_received_at') if result.get('cash_received_at') else None
            if result['cash_received_at']:
                result['cash_received']=amount(result.get('cash_received'),'cash_received')
                if result['cash_received']>result['company_receipts']+.02:raise ValueError('Collected retained-fee cash cannot exceed company_receipts')
                if moment(result['cash_received_at'])<moment(result['closed_at']):raise ValueError('cash_received_at cannot precede funded closing')
            elif result.get('cash_received') not in (None,0):raise ValueError('positive collected cash requires cash_received_at')
            else:result['cash_received']=None
            result['collected_cash']=result['cash_received']
            current=detail['current_settlement']
            if current and result.get('supersedes_event_id')!=current['id']:raise ValueError('A settlement correction must supersede the current settlement event')
            if result.get('supersedes_event_id') and (not current or result['supersedes_event_id']!=current['id']):raise ValueError('supersedes_event_id must identify this episode current settlement')
        elif kind=='note':result['text']=text(result.get('text'),'note text',100000)
        elif kind=='outcome':
            result['status']=result.get('status',result.get('outcome'))
            if result['status'] not in TERMINAL|{'open'}:raise ValueError('outcome must be closed, cancelled, expired or open')
            result['occurred_at']=iso(result.get('occurred_at') or stamp(),'occurred_at')
            if result['status']=='closed' and not detail['current_settlement']:raise ValueError('A funded settlement is required before a closed outcome')
            if result['status']=='closed' and moment(result['occurred_at'])<moment(detail['current_settlement']['closed_at']):raise ValueError('Closed outcome cannot precede funded settlement')
            if result['status'] in {'cancelled','expired'}:result['reason']=text(result.get('reason'),'reason')
            result['prior_state']={'stage':detail['episode']['stage'],'outcome':detail['episode'].get('outcome')}
        elif kind=='update':
            changes=result.get('changes')
            allowed={'stage','contract_date','deadline','asking_price','target_price','partner_id','buyer_id','state','capacity','meta'}
            if not isinstance(changes,dict) or not changes or set(changes)-allowed:raise ValueError('update changes must contain permitted episode fields')
            if changes.get('stage') in TERMINAL:raise ValueError('Record terminal stages using an outcome event')
            result['changes']=self._episode_fields(changes)
            result['reason']=text(result.get('reason'),'update reason')
            result['prior_state']={field:detail['episode'].get(field) for field in changes}
        elif kind=='action':
            result['action']=text(result.get('action',result.get('text')),'action',100000)
            if result.get('decision_id') and not any(d['id']==result['decision_id'] for d in detail['decisions']):raise ValueError('decision_id must refer to this episode decision')
        if 'synthetic' in result:result['synthetic']=boolean(result['synthetic'],'synthetic')
        return result

    def add_event(self,episode_id,data):
        if not isinstance(data,dict):raise ValueError('event must be an object')
        kind=data.get('kind',data.get('type'))
        if kind not in EVENT_KINDS:raise ValueError('unsupported event kind')
        payload=data.get('data',data.get('payload'))
        if payload is None:payload={key:value for key,value in data.items() if key not in {'id','event_id','kind','type','observed_at','available_at','recorded_at'}}
        identity=data.get('id',data.get('event_id')) or 'event-'+hashlib.sha256(encode({'episode_id':episode_id,'kind':kind,'data':payload,'observed_at':data.get('observed_at'),'available_at':data.get('available_at')}).encode()).hexdigest()[:32]
        identity=identifier(identity,'event id')
        with self.lock,self.db:
            detail=self.get_episode(episode_id)
            if not detail:raise ValueError('episode_id does not exist')
            existing=self.db.execute('SELECT * FROM brain_events WHERE id=?',(identity,)).fetchone()
            if existing:
                # Validate supplied raw payload against stored canonical input hash.
                stored=json.loads(existing['data'])
                stored_hash=stored.get('_input_sha256')
                request_hash=hashlib.sha256(encode({'kind':kind,'data':payload,'observed_at':data.get('observed_at'),'available_at':data.get('available_at')}).encode()).hexdigest()
                if existing['episode_id']!=episode_id or stored_hash!=request_hash:raise ValueError('event id already exists with different immutable contents')
                return self.event_item(existing)
            normalized=self._payload(kind,payload,detail)
            recorded=stamp();observed=iso(data.get('observed_at') or recorded,'observed_at');available=iso(data.get('available_at') or recorded,'available_at')
            if moment(observed)>moment(available):raise ValueError('observed_at cannot be later than available_at')
            if moment(available)>moment(recorded)+timedelta(minutes=5):raise ValueError('available_at cannot be in the future')
            for field in ('closed_at','cash_received_at','occurred_at','paid_at','completed_at'):
                if normalized.get(field) and moment(normalized[field])>moment(available):raise ValueError(field+' cannot be later than evidence availability')
            normalized['_input_sha256']=hashlib.sha256(encode({'kind':kind,'data':payload,'observed_at':data.get('observed_at'),'available_at':data.get('available_at')}).encode()).hexdigest()
            self.db.execute('INSERT INTO brain_events VALUES(?,?,?,?,?,?,?)',(identity,episode_id,kind,observed,available,recorded,encode(normalized)))
            return self.event_item(self.db.execute('SELECT * FROM brain_events WHERE id=?',(identity,)).fetchone())

    def add_rule(self,data):
        if not isinstance(data,dict):raise ValueError('rule version must be an object')
        result=clean_json(data,'rule')
        result['jurisdiction']=text(result.get('jurisdiction'),'jurisdiction',200)
        result['effective_from']=iso(result.get('effective_from'),'effective_from')
        if result.get('effective_to'):
            result['effective_to']=iso(result['effective_to'],'effective_to')
            if result['effective_to']<=result['effective_from']:raise ValueError('effective_to must be after effective_from')
        result['status']=result.get('status','draft')
        if result['status'] not in {'draft','reviewed'}:raise ValueError('rules must be draft or reviewed')
        if result['status']=='reviewed':result['approved_by']=text(result.get('approved_by'),'approved_by',200)
        if result.get('state'):
            result['state']=text(result['state'],'state',2).upper()
            if result['state'] not in STATES:raise ValueError('invalid state')
        rules=result.get('rules',result.get('constraints'))
        if not isinstance(rules,dict) or not rules:raise ValueError('rules must be a nonempty object of explicitly supplied requirements')
        for field in ('min_profit','partner_split_pct','capacity'):
            if field in rules:rules[field]=amount(rules[field],field)
        if rules.get('partner_split_pct',0)>100:raise ValueError('partner_split_pct must be <=100')
        for field in ('required_documents','allowed_structures'):
            if field in rules and (not isinstance(rules[field],list) or any(not isinstance(value,str) or not value.strip() for value in rules[field])):raise ValueError(field+' must be an array of strings')
        if 'deadline' in rules:
            rules['deadline']=iso(rules['deadline'],'deadline') if isinstance(rules['deadline'],str) else amount(rules['deadline'],'deadline')
        result['rules']=rules;result['constraints']=rules
        result['id']=identifier(result.get('id') or 'rule-'+hashlib.sha256(encode(result).encode()).hexdigest()[:24])
        result.setdefault('partner_id',None)
        with self.lock,self.db:
            existing=self.db.execute('SELECT * FROM brain_rules WHERE id=?',(result['id'],)).fetchone()
            if existing:
                if json.loads(existing['data'])!=result:raise ValueError('rule id already exists with different immutable contents; create a new version')
                return dict(result,recorded_at=existing['recorded_at'])
            recorded=stamp()
            self.db.execute('INSERT INTO brain_rules VALUES(?,?,?,?)',(result['id'],result['effective_from'],recorded,encode(result)))
            return dict(result,recorded_at=recorded)

    def rules(self,filters=None,**kwargs):
        filters=dict(filters or {},**kwargs)
        with self.lock:
            items=[dict(json.loads(row['data']),recorded_at=row['recorded_at']) for row in self.db.execute('SELECT * FROM brain_rules ORDER BY effective_from DESC,id')]
            for field in ('state','partner_id','status','jurisdiction'):
                if filters.get(field):items=[row for row in items if not row.get(field) or row.get(field)==filters[field]]
            if filters.get('as_of'):
                cutoff=iso(filters['as_of'],'as_of')
                items=[row for row in items if row['effective_from']<=cutoff and (not row.get('effective_to') or row['effective_to']>cutoff)]
            return {'items':items}

    def record_decision(self,episode_id,data):
        if not isinstance(data,dict):raise ValueError('decision must be an object')
        decision=clean_json(data,'decision')
        for field in ('prediction','recommendation','evidence_snapshot','model_versions'):
            if field not in decision:raise ValueError('decision requires '+field)
        if not isinstance(decision['evidence_snapshot'],dict) or not decision['evidence_snapshot']:raise ValueError('evidence_snapshot must be a nonempty object')
        if not isinstance(decision['model_versions'],(dict,list)):raise ValueError('model_versions must be an object or array')
        decision_at=iso(decision.get('decision_at') or stamp(),'decision_at')
        if moment(decision_at)>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('decision_at cannot be in the future')
        def inspect(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in {'available_at','observed_at'} and item and moment(item,key)>moment(decision_at):raise ValueError('Decision snapshot contains evidence unavailable at decision time')
                    inspect(item)
            elif isinstance(value,list):
                for item in value:inspect(item)
        inspect(decision['evidence_snapshot'])
        with self.lock,self.db:
            detail=self.get_episode(episode_id)
            if not detail:raise ValueError('episode_id does not exist')
            decision.setdefault('synthetic',detail['episode']['synthetic'])
            decision['synthetic']=boolean(decision['synthetic'],'synthetic') or detail['episode']['synthetic'] or contains_synthetic(decision['evidence_snapshot'])
            decision['decision_at']=decision_at
            decision_id=identifier(decision.get('id') or 'decision-'+hashlib.sha256(encode({'episode_id':episode_id,'data':data}).encode()).hexdigest()[:32])
            decision['id']=decision_id
            existing=self.db.execute('SELECT * FROM brain_decisions WHERE id=?',(decision_id,)).fetchone()
            if existing:
                prior=json.loads(existing['data'])
                if 'decision_at' not in data:decision['decision_at']=prior['decision_at']
                if existing['episode_id']!=episode_id or prior!=decision:raise ValueError('decision id already exists with different immutable contents')
                return self.decision_item(existing)
            recorded=stamp()
            self.db.execute('INSERT INTO brain_decisions VALUES(?,?,?,?,?)',(decision_id,episode_id,decision_at,recorded,encode(decision)))
            return self.decision_item(self.db.execute('SELECT * FROM brain_decisions WHERE id=?',(decision_id,)).fetchone())

    def portfolio_data(self):
        with self.lock:return {'episodes':[self.get_episode(row['id']) for row in self.db.execute('SELECT id FROM brain_episodes ORDER BY created_at,id')]}

    def model_rows(self,kind,as_of=None):
        kind={'time_to_close':'closing','time_to_cash':'cash'}.get(kind,kind)
        if kind not in {'valuation','repairs','acceptance','closing','cash','contribution'}:raise ValueError('unsupported training kind')
        cutoff=iso(as_of or stamp(),'as_of');rows=[]
        if moment(cutoff)>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('Training as_of cannot be in the future')
        with self.lock:
            for raw in self.db.execute('SELECT * FROM brain_decisions WHERE decision_at<=? ORDER BY decision_at,id',(cutoff,)):
                decision=self.decision_item(raw)
                snapshot=decision['evidence_snapshot']
                features=snapshot.get('features',decision.get('features'))
                if not isinstance(features,dict) or not features:continue
                detail=self.get_episode(decision['episode_id'],as_of=cutoff)
                events=[event for event in detail['events'] if event['available_at']>=decision['decision_at']]
                settlement=detail['current_settlement'];label=None;outcome_at=None;available_at=cutoff
                if kind=='closing':
                    outcomes=[event for event in events if event['kind']=='outcome' and event['status'] in TERMINAL]
                    terminal=outcomes[-1] if outcomes else None
                    if terminal:
                        outcome_at=terminal['occurred_at'];available_at=terminal['available_at'];status=terminal['status']
                    elif settlement and settlement['closed_at']>=decision['decision_at']:
                        outcome_at=settlement['closed_at'];available_at=settlement['available_at'];status='closed'
                    else:outcome_at=cutoff;status='censored'
                    days=(moment(outcome_at)-moment(decision['decision_at'])).total_seconds()/86400
                    if days<0:continue
                    label={'duration':days,'event':status}
                elif kind=='acceptance':
                    proposed=features.get('offered_price',features.get('offer_price',features.get('offered_amount')))
                    try:proposed=amount(proposed,'original offered price')
                    except ValueError:continue
                    offers=[event for event in events if event['kind']=='offer' and event['response'] in {'accepted','rejected'} and event['observed_at']>=decision['decision_at'] and abs(event['price']-proposed)<=.02]
                    if offers:
                        offer=offers[0];label=int(offer['response']=='accepted');outcome_at=offer['observed_at'];available_at=offer['available_at']
                elif kind=='cash':
                    if settlement and settlement.get('cash_received_at') and settlement.get('cash_received') is not None and settlement['available_at']>decision['decision_at'] and settlement['cash_received_at']>=decision['decision_at']:
                        label=(moment(settlement['cash_received_at'])-moment(settlement['closed_at'])).total_seconds()/86400
                        outcome_at=settlement['cash_received_at'];available_at=settlement['available_at']
                elif kind=='valuation':
                    if settlement and settlement['closed_at']>=decision['decision_at'] and settlement['available_at']>decision['decision_at']:
                        meta=settlement.get('meta',{})
                        label=meta.get('as_is_value',meta.get('sale_value'))
                        if label is not None:label=amount(label,'verified as-is sale value');outcome_at=settlement['closed_at'];available_at=settlement['available_at']
                elif kind=='repairs':
                    if settlement and settlement.get('meta',{}).get('actual_repairs') is not None and settlement['available_at']>decision['decision_at']:
                        label=amount(settlement['meta']['actual_repairs'],'actual_repairs');outcome_at=settlement['closed_at'];available_at=settlement['available_at']
                    else:
                        repairs=[event for event in events if event['kind']=='expense' and event['paid'] and event['type'] in {'repair','repairs'}]
                        completed=bool(settlement) or any(event['kind']=='milestone' and event['name'].lower() in {'repairs','repairs_complete','repairs_completed','repair completion'} and event['status'] in {'completed','cleared'} and event.get('verified') is True for event in events)
                        if repairs and completed:label=sum(event['amount'] for event in repairs);outcome_at=max(event.get('paid_at') or event['observed_at'] for event in repairs);available_at=max(event['available_at'] for event in repairs)
                elif kind=='contribution' and settlement:
                    label=settlement['company_receipts']-settlement['acquisition_costs']-settlement['transaction_costs'];outcome_at=settlement['closed_at'];available_at=settlement['available_at']
                if label is None:continue
                synthetic=bool(decision['synthetic'] or detail['episode']['synthetic'] or any(event.get('synthetic') is True for event in detail['events']))
                rows.append({'features':clean_json(features,'snapshot features'),'label':label,'decision_at':decision['decision_at'],'outcome_at':outcome_at,'available_at':available_at,'label_available_at':available_at,'recorded_at':decision['recorded_at'],'property_id':detail['episode']['property_id'],'episode_id':decision['episode_id'],'decision_id':decision['id'],'synthetic':synthetic})
        return rows
