"""Bounded, ephemeral generation jobs; no corpus writes or autonomous tool calls."""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from .corpus import fold, words

MODEL = 'qwen3:0.6b'
# Grammar and small, explicit translations of the controlled metadata labels.
GRAMMAR = set('a o as os um uma uns umas de da do das dos em no na nos nas e ou que qual quais como para por com ao aos sua seu suas seus se este esta esse essa isso isto ela ele elas eles entre segundo conforme fonte fontes argiloteca vocabulario identificado identificada identificador id nome preferido conhecido conhecida chamado chamada corresponde associado associada pertence classificado classificada categoria ingles portugues termo termos registro dados informa indica apresenta descreve trata respectivamente tambem e sao ser sendo tem pelo pela apenas mais sobre citado citada citados citadas descrito descrita descritos descritas'.split())


# Explicit PT/EN term equivalences support translation of English evidence.
# They authorize words only when their source-language counterparts are present.
TRANSLATIONS={
 'argila':{'clay','clays'},'argilas':{'clay','clays'},'minerais':{'minerals'},'mineral':{'mineral'},
 'particula':{'particle'},'particulas':{'particles'},'agua':{'water'},
 'suspensao':{'suspension'},'suspensoes':{'suspensions'},'estavel':{'stable'},'estaveis':{'stable'},
 'formadas':{'made','formed','composed'},'formados':{'made','formed','composed'},'compostas':{'composed','made'},
 'compostos':{'composed','made'},'formam':{'form','forms'},'forma':{'form','forms'},
 'esmectitas':{'smectites'},'esmectita':{'smectite'},'expandem':{'expand','expands'},'expansao':{'expansion'},
 'camadas':{'layers'},'camada':{'layer'},'entram':{'enter','enters'},'entra':{'enter','enters'},
 'estrutura':{'structure'},'estruturas':{'structures'},'superficie':{'surface'},'area':{'area'},
 'retencao':{'retention'},'retem':{'retain'},'adsorcao':{'adsorption'},'troca':{'exchange'},
 'cations':{'cations'},
 'elevada':{'high'},'alta':{'high'},'pequenas':{'small'},'pequenos':{'small'},
 'permitem':{'allow','enable'},'podem':{'can','may'},'solos':{'soils'},'sedimentos':{'sediments'},
 'lamelares':{'layered'},'interacao':{'interaction'},'interacoes':{'interactions'},'capacidade':{'capacity'}}
GRAMMAR.update('como assim isso estas esses essas esta isto porque elas eles por meio sua suas seus pela pelos pelas apresenta apresentam possui possuem permitem pode podem sao consiste consistem formacao'.split())


def narrative_excerpt(excerpt,question):
    clean=re.sub(r'(?<=\w)-\s*\n\s*(?=\w)','',excerpt)
    clean=' '.join(clean.split())
    candidates=[m.group(1) for m in re.finditer(r'(?<![\w])([A-ZÀ-Ý][^.!?]{20,420}[.!?])(?=\s|$)',clean)]
    if not candidates:raise ValueError('incomplete_evidence')
    anchors=set(words(question))-GRAMMAR
    ranked=[]
    for n,sentence in enumerate(candidates):
        bag=set(words(sentence));score=sum(t in bag or bool(TRANSLATIONS.get(t,set())&bag) for t in anchors)
        ranked.append((score,-n,sentence))
    score,_,best=max(ranked)
    if not score or score/max(len(anchors),1)<.8:raise ValueError('irrelevant_evidence')
    return best


def fingerprint(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare(question, sources):
    if not isinstance(question, str) or not 1 <= len(question) <= 180: raise ValueError('question_budget')
    if not isinstance(sources, list) or not sources or len(sources) > 4: raise ValueError('no_evidence')
    # One compact, numbered source keeps the CPU prompt small and prevents
    # blending facts from different minerals or samples. Full sources stay cited.
    source = sources[0];source_number=1
    primary = [s for s in sources if s.get('tipo_fonte')=='vocabulario' and s.get('vocabulary')!='grupo_mineralogico']
    if len(primary)>1: raise ValueError('structured_comparison')
    if source.get('derivation') in {'live_public_metadata_overview','live_public_metadata_fields','live_mineral_catalog'}: raise ValueError('structured_record')
    excerpt = source.get('excerpt', '')
    if not isinstance(excerpt, str) or not excerpt.strip(): raise ValueError('no_evidence')
    if 'ingles' in fold(question) and 'nome em ingles:' not in fold(excerpt): raise ValueError('missing_label_evidence')
    # A complete field/sentence boundary, never a silently cut numeric value.
    if source.get('numeric_validation') == 'pending_visual_review': raise ValueError('numeric_review')
    if source.get('tipo_fonte') == 'vocabulario':
        labels = dict(re.findall(r'(Nome preferido|Nome em inglês|Categoria|ID):\s*([^.]+)\.',excerpt))
        category = source.get('category')
        translations = {'species':'espécie mineral','group':'grupo mineralógico','family':'família mineralógica',
                        'series':'série mineralógica','material':'material','interstratified':'interestratificado'}
        if re.search(r'\b(familia|grupo|amplo|pertence)\b',fold(question)) and not re.search(r'\b(especie|serie|categoria)\b',fold(question)):
            raise ValueError('structured_relation')
        name=labels.get('Nome preferido')
        if not name or labels.get('Categoria')!=category or category not in translations: raise ValueError('controlled_category')
        if 'ingles' in fold(question):excerpt='Nome em inglês de '+name+': '+labels.get('Nome em inglês','')+'.'
        elif re.search(r'\b(id|identificador)\b',fold(question)):excerpt='Identificador de '+name+': '+labels.get('ID','')+'.'
        else:excerpt=name+': '+translations[category]+'.'
        limit = 180
    else:
        for number,candidate in enumerate(sources,1):
            if candidate.get('numeric_validation')=='pending_visual_review':continue
            try:readable=narrative_excerpt(candidate.get('excerpt',''),question)
            except ValueError:continue
            source=candidate;excerpt=readable;source_number=number;break
        else:raise ValueError('irrelevant_evidence')
        limit=420
    quote = excerpt[:limit]
    boundary = max(quote.rfind('. '), quote.rfind('; '), quote.rfind('\n'))
    if boundary > 65 and len(excerpt) > limit: quote = quote[:boundary+1]
    if len(quote) < 20: raise ValueError('evidence_budget')
    return {'question': question, 'quote': quote, 'source': source, 'source_number': source_number}


def validate_answer(answer, plan):
    """Conservative publication gate; ambiguous paraphrases fall back to excerpts."""
    if not isinstance(answer, str): raise ValueError('invalid_output')
    answer = answer.replace('**', '').strip()
    if plan.get('source',{}).get('tipo_fonte')!='vocabulario':
        # A tiny model may copy the English subject/verb before translating the
        # rest. Normalize only these exact, unambiguous glossary phrases.
        for pattern,replacement in ((r'^Clays form\b','As argilas formam'),(r'^Clays are\b','As argilas são'),(r'^Clay is\b','A argila é'),(r'^Clay minerals are\b','Os argilominerais são')):
            answer=re.sub(pattern,replacement,answer,flags=re.I)
        answer=re.sub(r'(\[Fonte [1-4]\])\.(?=\s|$)',r'\1',answer)

    if not re.search(r'\b(é|são|uma|você|consulte|seu|sua|este|esta|permite|formam|apresentam|possuem|podem|expandem)\b',answer,re.I): raise ValueError('portuguese_required')
    marker='[Fonte '+str(plan.get('source_number',1))+']'
    number=str(plan.get('source_number',1))
    if not 15 <= len(answer) <= 650 or not re.search(r'[.!?](?:\s*'+re.escape(marker)+r')?\s*$', answer): raise ValueError('incomplete_output')
    refs = re.findall(r'\[Fonte (\d+)\]', answer)
    if not refs or set(refs) != {number} or '[' in answer.replace(marker,''): raise ValueError('invalid_citation')
    content = answer.replace(marker,'').strip()
    if content.endswith('?') or fold(content) == fold(plan['question']): raise ValueError('question_echo')
    if re.search(r'<|>|https?://|```|\b(ignore|instrucoes|sistema|assistant|system|user|resposta:)\b', fold(content)): raise ValueError('unsafe_output')
    quote = fold(plan['quote']); normalized = fold(content)
    if re.search(r'\b(nao|nunca|sempre|cura|curar|comprova|confirmado|confirma|diagnostico)\b', normalized): raise ValueError('unsupported_assertion')
    source = plan['source']
    if source.get('tipo_fonte')!='vocabulario' and re.search(r'\b(are|is|the|that|which|with|made|particles|suspensions|water|form|stable|because)\b',normalized):raise ValueError('mixed_language')
    bag = set(words(plan['quote'] + ' ' + source.get('excerpt','') + ' ' + source.get('title', '')))
    # Lexical overlap alone cannot detect swapped labels (e.g. claiming the
    # Portuguese name is the English name). Enforce controlled field values.
    if source.get('tipo_fonte') == 'vocabulario':
        full = fold(source['excerpt'])
        english = re.search(r'nome em ingles:\s*([^.]+)',full)
        if english and ('ingles' in normalized or 'ingles' in fold(plan['question'])):
            expected = english[1].strip()
            if not re.search(r'(?<!\w)'+re.escape(expected)+r'(?!\w)',normalized): raise ValueError('english_label_conflict')
            assigned = re.search(r'\bingles(?:\s+d[ao]\s+[^.!?]{1,60}?)?\s*(?:\be\b|:)\s*["\']?([\w-]+)',normalized)
            if assigned and assigned[1] != expected.split()[0]: raise ValueError('english_label_conflict')
        identifier = re.search(r'\bid:\s*([a-z0-9_-]+)',full)
        preferred = re.search(r'nome preferido:\s*([^.]+)',full)
        assigned_pt = re.search(r'\b(?:portugues|preferido)\s*(?:e\s+)?[:=]?\s*["\']?([\w-]+)',normalized)
        if preferred and assigned_pt and assigned_pt[1] != preferred[1].strip().split()[0]: raise ValueError('preferred_label_conflict')
        assigned_id = re.search(r'\b(?:id|identificador)\s*(?:e\s+)?[:=]?\s*["\']?([a-z0-9_-]+)',normalized)
        if identifier and assigned_id and assigned_id[1] != identifier[1]: raise ValueError('identifier_conflict')
    allowed = bag | GRAMMAR
    if source.get('tipo_fonte')!='vocabulario':allowed |= {pt for pt,en in TRANSLATIONS.items() if en & set(words(plan['quote']))}
    category = source.get('category')
    if category == 'species': allowed |= {'especie', 'especies', 'mineral', 'minerais', 'argilomineral', 'argilominerais'}
    if category in {'group', 'family'}: allowed |= {'grupo', 'grupos', 'familia'}
    if category == 'material': allowed |= {'material'}
    if category == 'series': allowed |= {'serie','series','mineralogica','mineralogico'}
    if category in {'group','family'}: allowed |= {'mineralogico','mineralogica'}
    tokens = set(words(content))
    if tokens - allowed: raise ValueError('unsupported_terms:' + ','.join(sorted(tokens - allowed)[:5]))
    numbers = set(re.findall(r'\d+(?:[.,]\d+)?', content))
    if not numbers <= set(re.findall(r'\d+(?:[.,]\d+)?', plan['quote'])): raise ValueError('unsupported_number')
    if category != 'species' and re.search(r'\be (?:uma )?especie\b',normalized): raise ValueError('category_conflict')
    if category not in {'group','family'} and re.search(r'\be (?:um |uma )?(?:grupo|familia)\b',normalized): raise ValueError('category_conflict')
    if category == 'species' and re.search(r'\b(?:e|como) (?:um |uma )?(?:grupo|familia|material)\b', normalized): raise ValueError('category_conflict')
    # Each sentence needs its own source marker. Decimal dots and IDs are not
    # split; a final marker may follow the sentence punctuation.
    sentences = re.split(r'(?<=\])\s+(?=[A-ZÁÉÍÓÚ])', answer)
    if any(marker not in s for s in sentences): raise ValueError('uncited_sentence')
    if len(tokens & (bag - GRAMMAR)) < 1 and not any(TRANSLATIONS.get(t,set()) & bag for t in tokens): raise ValueError('no_source_anchor')
    return answer


class Jobs:
    def __init__(self, enabled=None, runner=None, budget=90, ttl=300):
        self.enabled = os.getenv('ARGILOCLAY_ASYNC_GENERATION') == '1' if enabled is None else enabled
        self.runner = runner or self._run; self.budget = min(max(budget, 1), 90); self.ttl = ttl
        self.lock = threading.RLock(); self.rows = {}; self.active = None

    def submit(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'question','sources','language','budget_seconds','limitations'}: raise ValueError('Payload inválido.')
        sources = payload.get('sources'); question = payload.get('question')
        if not isinstance(sources, list) or len(sources)>4 or len(json.dumps(sources)) > 60000 or any(not isinstance(s,dict) or not isinstance(s.get('excerpt'),str) or len(s['excerpt'])>6000 for s in sources): raise ValueError('Fontes acima do limite.')
        limitations=payload.get('limitations',[])
        if not isinstance(limitations,list) or len(limitations)>12 or any(not isinstance(s,str) or len(s)>1000 for s in limitations): raise ValueError('Limitações inválidas.')
        if not self.enabled: return {'state':'fallback','reason':'disabled'}
        if payload.get('language', 'pt') != 'pt': return {'state':'fallback','reason':'language'}
        try: plan = prepare(question, sources)
        except ValueError as exc: return {'state':'fallback','reason':str(exc)}
        requested = payload.get('budget_seconds', self.budget)
        if isinstance(requested, bool) or not isinstance(requested,(int,float)): raise ValueError('Prazo inválido.')
        with self.lock:
            now = time.monotonic()
            self.rows = {k:v for k,v in self.rows.items() if now-v['created'] < self.ttl}
            if self.active or len(self.rows) >= 32: return {'state':'fallback','reason':'busy'}
            key = secrets.token_hex(16); deadline = now + min(max(requested,1),self.budget)
            row = {'id':key,'state':'pending','created':now,'deadline':deadline,'cancel':threading.Event(),
                   'sources':sources,'plan':plan,'sources_fingerprint':fingerprint(sources),'limitations':limitations}
            self.rows[key] = row; self.active = key
            threading.Thread(target=self._work,args=(row,),daemon=True,name='argiloclay-generation').start()
            return {'state':'pending','job_id':key,'deadline_seconds':round(deadline-now,2),'model':MODEL}

    def _work(self, row):
        try:
            answer = self.runner(row['plan'], row['cancel'], row['deadline'])
            if time.monotonic() >= row['deadline']: raise TimeoutError()
            answer = validate_answer(answer, row['plan'])
            with self.lock:
                if row['cancel'].is_set(): return
                row.update(state='complete',generated_answer=answer,validated=True,
                           elapsed_ms=round((time.monotonic()-row['created'])*1000,2))
        except Exception as exc:
            with self.lock:
                code = str(exc).split(':')[0]
                if not re.fullmatch(r'[a-z_]{1,40}',code): code='model_failure'
                if not row['cancel'].is_set(): row.update(state='fallback',reason='timeout' if isinstance(exc,TimeoutError) else 'validation_or_model_failure',validation_code=code)
        finally:
            with self.lock:
                if self.active == row['id']: self.active = None

    def _run(self, plan, cancelled, deadline):
        env = dict(os.environ); env['PYTHONDONTWRITEBYTECODE']='1'
        process = subprocess.Popen([sys.executable,'-m','argiloclay_intelligence.generation_worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env)
        try:
            process.stdin.write(json.dumps(plan,ensure_ascii=False).encode());process.stdin.close();process.stdin=None
            while process.poll() is None:
                if cancelled.is_set() or time.monotonic() >= deadline: raise TimeoutError()
                time.sleep(.05)
            raw = process.stdout.read(16001)
            if process.returncode or len(raw)>16000: raise ValueError('worker_failure')
            return json.loads(raw)['answer']
        finally:
            if process.poll() is None: process.kill()
            process.wait(timeout=3)
            if process.stdout: process.stdout.close()

    def get(self, key):
        with self.lock:
            row = self.rows.get(key)
            if not row or time.monotonic()-row['created'] >= self.ttl: raise KeyError(key)
            if row['state']=='pending' and time.monotonic() >= row['deadline']:
                row['cancel'].set();row.update(state='fallback',reason='timeout')
            keys = ('state','reason','generated_answer','validated','elapsed_ms','sources_fingerprint','sources','validation_code','limitations')
            result={k:row[k] for k in keys if k in row}
            result['question']=row['plan']['question']
            return result

    def cancel(self, key):
        with self.lock:
            row = self.rows.get(key)
            if not row: raise KeyError(key)
            row['cancel'].set();row.update(state='cancelled',reason='cancelled');row.pop('generated_answer',None)
            return {'state':'cancelled'}
