"""Offline NLP retrieval and transparent locally trainable opportunity classification."""
from __future__ import annotations
import collections
import hashlib
import json
import math
import os
import random
import re
import threading
from pathlib import Path

FEATURES = ('equity_pct', 'discount_pct', 'repair_ratio', 'ltv', 'days_on_market', 'tax_delinquent', 'permit_count')
SCALES = (1, 1, 1, 1, 365, 1, 10)
STOP = set('the a an to of and for in is are be on with by as or this that from at it have has you your'.split())

def tokens(text):
    return [t for t in re.findall(r'[a-z0-9]{2,}', text.lower()) if t not in STOP]

def sigmoid(x):
    return 1 / (1 + math.exp(-max(-35, min(35, x))))

def vector(features):
    if not isinstance(features,dict):
        raise ValueError('Features must be an object')
    vals = []
    for name, scale in zip(FEATURES, SCALES):
        value = features.get(name, 0)
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Features must be finite numbers: ' + name)
        vals.append(max(-5, min(5, float(value) / scale)))
    return vals

class KnowledgeIndex:
    """TF-IDF cosine search over the local Obsidian vault. No embeddings API."""
    def __init__(self, root):
        self.root = Path(root)
        self.documents = []
        self.df = collections.Counter()
        self._lock = threading.RLock()
        self.build()

    def build(self):
        docs, df = [], collections.Counter()
        for path in sorted(self.root.rglob('*.md')):
            if path.stat().st_size > 2_000_000:
                continue
            content = path.read_text(encoding='utf-8')
            title = re.search(r'^#\s+(.+)$', content, re.M)
            title = title.group(1) if title else path.stem
            count = collections.Counter(tokens(title + ' ' + content))
            df.update(count.keys())
            docs.append({'path': path.relative_to(self.root).as_posix(), 'title': title,
                         'content': content, 'counts': count})
        n = len(docs)
        idf = {term: math.log((1 + n) / (1 + freq)) + 1 for term, freq in df.items()}
        for doc in docs:
            weights = {t: (1 + math.log(c)) * idf[t] for t, c in doc['counts'].items()}
            doc['weights'] = weights
            doc['norm'] = math.sqrt(sum(w*w for w in weights.values())) or 1
        with self._lock:
            self.documents, self.df, self.idf = docs, df, idf
        return {'documents': n, 'terms': len(idf)}

    def search(self, query, limit=10):
        if not isinstance(query,str):
            raise ValueError('Query must be a string')
        if len(query) > 4000:
            raise ValueError('Query exceeds 4000 characters')
        with self._lock:
            counts = collections.Counter(tokens(query))
            weights = {t: (1 + math.log(c)) * self.idf[t] for t, c in counts.items() if t in self.idf}
            norm = math.sqrt(sum(w*w for w in weights.values())) or 1
            results = []
            for doc in self.documents:
                score = sum(w * doc['weights'].get(t, 0) for t, w in weights.items()) / (norm * doc['norm'])
                if score <= 0:
                    continue
                content = doc['content']
                matches = [content.lower().find(t) for t in weights]
                at = min((m for m in matches if m >= 0), default=0)
                snippet = re.sub(r'\s+', ' ', content[max(0, at-80):at+400])
                results.append({'path': doc['path'], 'title': doc['title'], 'score': round(score, 5),
                                'snippet': snippet, 'content': content})
            results.sort(key=lambda d: (-d['score'], d['path']))
            return {'results': results[:max(1, min(50, int(limit)))], 'total': len(results),
                    'method': 'local_tf_idf_cosine', 'indexed_documents': len(self.documents)}

class OpportunityModel:
    """L2 regularized logistic regression with reproducible holdout evaluation."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.model = None
        if self.path.exists():
            self.model = json.loads(self.path.read_text())

    def train(self, rows, synthetic=False, epochs=200):
        if not isinstance(rows,list):
            raise ValueError('Training rows must be an array')
        if not isinstance(synthetic,bool):
            raise ValueError('Synthetic must be a boolean')
        if not isinstance(epochs,int) or isinstance(epochs,bool):
            raise ValueError('Epochs must be an integer')
        if not 20 <= len(rows) <= 100_000:
            raise ValueError('Training requires 20 to 100000 labeled rows')
        examples = []
        for row in rows:
            if not isinstance(row,dict):
                raise ValueError('Each training row must be an object')
            if 'synthetic' in row and not isinstance(row['synthetic'],bool):
                raise ValueError('Row synthetic flags must be booleans')
            synthetic = synthetic or row.get('synthetic',False)
            features = row.get('features',{})
            if not isinstance(features,dict):
                raise ValueError('Features must be an object')
            if 'synthetic' in features:
                if not isinstance(features['synthetic'],bool):
                    raise ValueError('Feature synthetic flags must be booleans')
                synthetic = synthetic or features['synthetic']
            label = row.get('label')
            if label not in (0, 1):
                raise ValueError('Label must be 0 or 1')
            examples.append((vector(features), int(label)))
        if len({y for _, y in examples}) < 2:
            raise ValueError('Training requires both positive and negative outcomes')
        # Deduplicate to avoid repeated observations leaking across the split.
        unique = list(dict.fromkeys((tuple(x), y) for x, y in examples))
        labels_by_vector = {}
        for x,y in unique:
            if x in labels_by_vector and labels_by_vector[x] != y:
                raise ValueError('Identical feature vectors have conflicting labels; resolve outcomes before training')
            labels_by_vector[x] = y
        if len(unique) < 20:
            raise ValueError('Training requires 20 unique labeled feature vectors')
        groups = {0: [], 1: []}
        for x, y in unique:
            groups[y].append((x, y))
        if min(len(group) for group in groups.values()) < 3:
            raise ValueError('Training requires at least 3 unique examples of each class')
        rng = random.Random(101)
        train, test = [], []
        for group in groups.values():
            rng.shuffle(group)
            k = max(1, len(group)//5)
            test.extend(group[:k]); train.extend(group[k:])
        weights = [0.0] * len(FEATURES)
        bias = 0.0
        for _ in range(max(10, min(400, epochs))):
            grads = [0.0] * len(weights)
            bgrad = 0.0
            for x, y in train:
                residual = sigmoid(bias + sum(w*v for w,v in zip(weights,x))) - y
                bgrad += residual
                for i, value in enumerate(x):
                    grads[i] += residual * value
            lr = 0.3
            weights = [w-lr*(g/len(train)+0.01*w) for w,g in zip(weights,grads)]
            bias -= lr*bgrad/len(train)
        pairs = [(sigmoid(bias + sum(w*v for w,v in zip(weights,x))), y) for x,y in test]
        accuracy = sum((p>=0.5)==bool(y) for p,y in pairs)/len(pairs)
        brier = sum((p-y)**2 for p,y in pairs)/len(pairs)
        fingerprint = hashlib.sha256(json.dumps(unique, sort_keys=True).encode()).hexdigest()
        model = {'model_id': 'logistic-'+fingerprint[:12], 'algorithm': 'l2_logistic_regression',
                 'features': list(FEATURES), 'scales': list(SCALES), 'weights': weights, 'bias': bias,
                 'trained_on': len(unique), 'train_rows': len(train), 'holdout_rows': len(test),
                 'synthetic': bool(synthetic), 'data_sha256': fingerprint,
                 'metrics': {'holdout_accuracy': round(accuracy, 4), 'holdout_brier': round(brier, 4)},
                 'limitations': 'Training contains synthetic data; not validated against real closings.' if synthetic else
                     'User supplied labels; random holdout only. Validate out of time and by market before reliance.'}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(model, indent=2))
            os.replace(temp, self.path)
            self.model = model
        return {k:v for k,v in model.items() if k not in ('weights','bias')}

    def train_reference(self):
        rng = random.Random(101)
        rows = []
        for _ in range(3000):
            f = {'equity_pct': rng.random(), 'discount_pct': rng.uniform(-0.2, 0.5),
                 'repair_ratio': rng.uniform(0, 0.5), 'ltv': rng.random(),
                 'days_on_market': rng.randrange(365), 'tax_delinquent': rng.randrange(2),
                 'permit_count': rng.randrange(11)}
            # Simulation ground truth for demonstrating a functioning ML pipeline.
            margin = 3*f['discount_pct'] + 1.5*f['equity_pct'] - 2*f['repair_ratio'] - f['ltv'] - 0.4
            y = int(rng.random() < sigmoid(4*margin))
            rows.append({'features':f, 'label':y})
        return self.train(rows, synthetic=True)

    def predict(self, features):
        with self.lock:
            if not self.model:
                raise ValueError('No trained model. Train with labels or initialize the synthetic reference.')
            x = vector(features)
            m = self.model
            probability = sigmoid(m['bias'] + sum(w*v for w,v in zip(m['weights'],x)))
            return {'probability':round(probability,6), 'model_id':m['model_id'],
                    'trained_on':m['trained_on'], 'synthetic':m['synthetic'],
                    'limitations':m['limitations'], 'contributions':dict(zip(FEATURES,[round(w*v,6) for w,v in zip(m['weights'],x)]))}

    def status(self):
        with self.lock:
            if not self.model:
                return {'models':[], 'status':'untrained'}
            return {'models':[{k:v for k,v in self.model.items() if k not in ('weights','bias')}], 'status':'ready'}

def extract(text):
    """Rule-based document NLP. Evidence candidates require human review."""
    if not isinstance(text,str) or len(text)>2_000_000:
        raise ValueError('Text must be a string below 2 MB')
    patterns = {'money':r'\$\s*\d[\d,]*(?:\.\d{1,2})?(?:\s*(?:million|billion|MM|M))?',
                'dates':r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b',
                'parcel_ids':r'(?i)\b(?:APN|parcel(?:\s+number)?|parcel\s+id)\s*[:#]?\s*([A-Z0-9][A-Z0-9 .-]{3,35})',
                'zoning':r'(?i)\bzoning\s*[:=]?\s*([A-Z][A-Z0-9-]{1,12})'}
    return {'entities':{key:list(dict.fromkeys(re.findall(p,text)))[:200] for key,p in patterns.items()},
            'method':'local_rules', 'review_required':True}
