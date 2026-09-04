
from __future__ import annotations
from pathlib import Path
import os, sys, json, time, traceback, statistics, requests, re, shutil, zipfile, argparse, hashlib, copy
from concurrent.futures import ThreadPoolExecutor

# Runtime paths are initialized in main().
ROOT=Path(__file__).resolve().parents[1]
RUN=None
OUT=None
LOG=None
VALID_TIERS={'A1','A2','A3','N'}; VALID_QUALITY={'full','substantial','limited','attribute_conflict','core_conflict','none'}; VALID_REL={'equivalent','part-whole','incompatible',None}; VALID_DETAILS={'equivalent','partial','conflicting','absent',None}
QUALITY_CREDIT={'full':1.0,'substantial':0.90,'attribute_conflict':0.75,'limited':0.60,'core_conflict':0.25,'none':0.0}
LOCAL_FLOOR_NON_CORE=0.5
EN_ABNORMAL_KEYWORDS=['mass','nodule','opacity','effusion','thickening','enlarged','enlargement','calcification','stenosis','obstruction','consolidation','atelectasis','dilatation','dilation','decreased density','increased density','lesion','edema','hemorrhage','fracture','metastasis','invasion','stranding','fat-density','defect','filling defect','thrombus','embolism','embolus','cavity','cavitation','abscess','air-fluid','malignancy','tumor','tumour','infiltration','collapse']
CN_ABNORMAL_KEYWORDS=['肿块','占位','结节','微结节','小结节','磨玻璃','实性','密度影','高密度','低密度','斑片','条索','索条','实变','渗出','炎症','肺炎','肺不张','膨胀不全','透亮','囊状','空洞','气液平','积液','胸水','腹水','气胸','增厚','增大','肿大','强化','钙化','狭窄','扩张','梗阻','受压','包绕','侵犯','转移','水肿','出血','血肿','骨折','缺血','梗死','穿孔','游离气体','充盈缺损','血栓','栓塞','夹层','脓肿','脓胸','塌陷','萎陷','脂肪密度','脂肪浸润','脂肪肝']
ABNORMAL_KEYWORDS=EN_ABNORMAL_KEYWORDS+CN_ABNORMAL_KEYWORDS
POSITIVE_ABNORMAL_PATTERNS=EN_ABNORMAL_KEYWORDS+['calcified']+CN_ABNORMAL_KEYWORDS
CN_NEG_MARKERS=['未见','未显示','未发现','未及','未提示','无明显','无异常','无','不大','不增大','不增宽','未增宽','不扩张','无扩张','无狭窄','无充盈缺损','未见充盈缺损','阴性','正常','通畅','无殊','未见明显']
CN_POSITIVE_CUES=['见','可见','显示','提示','考虑','伴','形成','呈','增厚','增大','肿大','强化','狭窄','扩张','受压','包绕','侵犯','充盈缺损','密度增高','密度减低']
CN_HISTORY_MARKERS=['病史','既往','确诊','术后复查','复查','随访','治疗后','检查目的','临床诊断','请结合临床']
CN_IMAGING_MARKERS=['见','可见','显示','提示','密度','信号','强化','结节','肿块','占位','积液','增厚','增大','狭窄','扩张','充盈缺损']

def log(msg):
    line=f"[{time.strftime('%F %T')}] {msg}"; print(line, flush=True)
    with LOG.open('a',encoding='utf-8') as f: f.write(line+'\n')
def parse_env_file(p):
    out={}
    for line in p.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1); out[k.strip()]=v.strip().strip('"').strip("'")
    return out
def read_jsonl(p): return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]
def write_jsonl(p, rows): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
def clean_json_text(text):
    text=(text or '').strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if lines and lines[0].startswith('```'): lines=lines[1:]
        if lines and lines[-1].strip()=='```': lines=lines[:-1]
        text='\n'.join(lines).strip()
    return text
def render(tpl, **kw):
    for k,v in kw.items(): tpl=tpl.replace('{'+k+'}', str(v))
    return tpl
def pmap(fn, items, workers):
    if workers<=1: return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=workers) as pool: return list(pool.map(fn,items))
class Client:
    def __init__(self,cfg): self.cfg=cfg
    def complete(self,prompt):
        last=None
        for attempt in range(1,self.cfg['max_retries']+1):
            try:
                payload={'model':self.cfg['model'],'messages':[{'role':'user','content':prompt}],'max_tokens':self.cfg['max_tokens']}
                # temperature omitted intentionally
                r=requests.post(self.cfg['base_url'],headers={'Content-Type':'application/json','Authorization':f"Bearer {self.cfg['api_key']}",'Accept':'application/json'},json=payload,timeout=self.cfg['timeout_seconds'])
                r.raise_for_status(); data=r.json(); content=(data.get('choices') or [{}])[0].get('message',{}).get('content')
                if not isinstance(content,str) or not content.strip(): raise RuntimeError('empty content')
                return content
            except Exception as e:
                last=e; log(f'API retry {attempt}/{self.cfg["max_retries"]}: {type(e).__name__}: {e}')
                if attempt<self.cfg['max_retries']: time.sleep(min(2**(attempt-1),8))
        raise RuntimeError(last)
def llm_json(client,prompt,tag):
    txt=client.complete(prompt)
    try: return json.loads(clean_json_text(txt))
    except Exception:
        (RUN/f'bad_{tag}_{int(time.time())}.txt').write_text(txt,encoding='utf-8'); raise

def validate_sru(record,obj,prefix):
    units=obj.get('semantic_units')
    if not isinstance(units,list): raise ValueError('semantic_units must be list')
    out=[]; seen=set()
    for i,u in enumerate(units,1):
        if not isinstance(u,dict): raise ValueError('unit must be object')
        uid=str(u.get('id') or f'{prefix}{i:03d}')
        if not uid.startswith(prefix): uid=f'{prefix}{i:03d}'
        if uid in seen: uid=f'{prefix}{i:03d}'
        seen.add(uid)
        sent=str(u.get('sentence','')).strip(); core=str(u.get('core_assertion','')).strip()
        if not sent: raise ValueError(f'empty SRU sentence {uid}')
        if not core: core=sent
        key_attrs=u.get('key_attributes') if isinstance(u.get('key_attributes'),list) else []
        minor_attrs=u.get('minor_attributes') if isinstance(u.get('minor_attributes'),list) else []
        details=u.get('dependent_details') if isinstance(u.get('dependent_details'),list) else []
        key_attrs=[str(x) for x in key_attrs]; minor_attrs=[str(x) for x in minor_attrs]; details=[str(x) for x in details]
        if not details: details=key_attrs+minor_attrs
        kind=u.get('unit_kind') if u.get('unit_kind') in {'independent_assertion','normal_negative','technical_or_limited_quality'} else 'independent_assertion'
        cand={'id':uid,'sentence':sent,'core_assertion':core,'key_attributes':key_attrs,'minor_attributes':minor_attrs,'dependent_details':details,'unit_kind':kind,'merge_rationale':str(u.get('merge_rationale',''))}
        # Generic guard: indication/history/follow-up labels are context, not imaging findings.
        if likely_history_only_sru(cand):
            continue
        out.append(cand)
    meta={k:record.get(k) for k in ['model','case_id','original_name','repeat_id','selection_reason','category','selection_model_tier','model_original_mean','original_radcise_score','original_guard_warning_count','original_guard_warning_ratio'] if k in record}
    return {'name':record['name'],'Examined_Area':record.get('Examined_Area',''),'Examined_Type':record.get('Examined_Type',''),'rewritten_report':str(obj.get('rewritten_report',record.get('English_Report',''))),'semantic_units':out, **meta}
def fmt_srus(row):
    return json.dumps([{'id':u.get('id'),'sentence':u.get('sentence'),'core_assertion':u.get('core_assertion',''),'key_attributes':u.get('key_attributes',[]),'minor_attributes':u.get('minor_attributes',[]),'dependent_details':u.get('dependent_details',[]),'unit_kind':u.get('unit_kind','')} for u in row.get('semantic_units',[])],ensure_ascii=False,indent=2)

def parse_bool_or_none(v):
    if isinstance(v,bool): return v
    if isinstance(v,str):
        s=v.strip().lower()
        if s in {'true','yes','1'}: return True
        if s in {'false','no','0'}: return False
    return None

def _norm(text):
    return ' '+re.sub(r'\s+',' ',(text or '').lower())+' '

def _contains_any(text, terms):
    return any(k in text for k in terms)

def _clauses(text):
    return [c.strip() for c in re.split(r'[.;,，。；、\n]|\bbut\b|\bwhile\b|\balthough\b|\bwhereas\b|\bexcept\b|但|但是|而|然而|除外|此外|另见|伴', _norm(text)) if c.strip()]

def _has_neg_marker(t):
    t=_norm(t)
    en=bool(re.search(r'\b(no|without|absent|absence of|not seen|not visualized|no obvious|no definite|normal|unremarkable|nondilated|not dilated|patent)\b', t))
    cn=_contains_any(t, CN_NEG_MARKERS)
    return en or cn

def _has_cn_positive_cue(t):
    return _contains_any(t, CN_POSITIVE_CUES)

def has_positive_abnormal_signal(text):
    """True when at least one clause asserts a positive abnormality rather than only denying one.
    Bilingual polarity guard for English/Chinese reports. A positive abnormal clause should not be
    downgraded to N merely because another clause contains a negative qualifier.
    """
    for cl in _clauses(text):
        if any(p in cl for p in POSITIVE_ABNORMAL_PATTERNS):
            if not _has_neg_marker(cl):
                return True
            # Chinese/English positive cues can override a distant negation only when the clause is not an explicit "no X" statement.
            neg_then_abn = _has_neg_marker(cl) and any((neg in cl and term in cl and cl.find(neg) < cl.find(term)) for neg in CN_NEG_MARKERS+['no','without','absent','not seen','no obvious','no definite'] for term in POSITIVE_ABNORMAL_PATTERNS if term in cl)
            if _has_cn_positive_cue(cl) and not neg_then_abn:
                return True
            if re.search(r'\b(seen|present|identified|demonstrates|shows|with|compatible with|suggestive of|consistent with)\b', cl) and not re.search(r'\b(no|without|absent|absence of|not seen|not visualized|no obvious|no definite)\b.*\b('+'|'.join(re.escape(p) for p in EN_ABNORMAL_KEYWORDS)+r')\b', cl):
                return True
    return False

def likely_negated_abnormal_phrase(text):
    """Return True when abnormal terms occur only in explicit negative/normal context."""
    t=_norm(text)
    if not any(k in t for k in ABNORMAL_KEYWORDS):
        return True
    if has_positive_abnormal_signal(t):
        return False
    return _has_neg_marker(t)


def critical_dependent_phrase(text):
    """Generic safety/staging modifiers that can justify A2/A1 for a dependent local/fluid effect."""
    t=_norm(text)
    critical_terms=[
        'severe','marked','complete','complete collapse','lobar collapse','atelectatic collapse',
        'major','mass effect','mediastinal shift','midline shift','occlusion','occluded',
        'invasion','invades','encasement','encases','thrombosis','thrombus',
        'high-grade','critical stenosis','perforation','free air','hemorrhage','hemothorax',
        'tension','infected','empyema','large effusion','moderate effusion','loculated',
        'pneumothorax','hydropneumothorax','pleural air','drain','drainage tube','postoperative','post-surgical','post surgical','postoperative bed','volume loss',
        '重度','明显','显著','完全','肺叶不张','压迫','占位效应','纵隔移位','中线移位','闭塞','侵犯','包绕','血栓','栓塞','高度狭窄','严重狭窄','穿孔','游离气体','出血','血胸','张力性','感染性','脓胸','大量积液','中等量积液','中量积液','包裹性积液','气胸','液气胸','胸腔积气','积气','引流管','术后','术区','手术后','术腔','肺体积缩小','膨胀不全'
    ]
    return any(k in t for k in critical_terms)

def low_volume_or_unspecified_fluid(text):
    t=_norm(text)
    if not any(k in t for k in ['effusion','fluid','pleural fluid','ascites','积液','胸水','腹水','液体']):
        return False
    if any(k in t for k in ['large effusion','moderate effusion','mass effect','tension','hemothorax','empyema','infected','loculated','大量积液','大量胸腔积液','大量腹水','中等量积液','中量积液','中等量胸腔积液','中量胸腔积液','占位效应','张力性','血胸','脓胸','感染性','包裹性']):
        return False
    return any(k in t for k in ['small','trace','minimal','tiny','slight','little','少量','少许','微量','少量的','少许的','轻度'])

def positive_nodal_concept(text):
    """Generic nodal-status guard: promote only clearly abnormal/suspicious nodal findings, not merely small/nonspecific nodes."""
    t=_norm(text)
    if _has_neg_marker(t):
        return False
    en=bool(re.search(r'\b(enlarged|enlargement|suspicious|abnormal|pathologic|metastatic|metastasis|rounded|necrotic|irregular|short[- ]?axis|short axis)\b', t))
    cn=any(k in t for k in ['淋巴结肿大','肿大淋巴结','增大淋巴结','异常淋巴结','可疑转移淋巴结','转移性淋巴结','坏死淋巴结','融合淋巴结','短径增大','形态异常'])
    return en or cn

def safety_critical_conflict_text(text):
    """Generic acute/safety-critical vocabulary for conflict ceiling; intentionally disease-agnostic."""
    t=_norm(text)
    en=bool(re.search(r'\b(acute|hemorrhage|bleeding|hematoma|contusion|laceration|trauma|traumatic|fracture|ischemia|infarct|perforation|free air|rupture|torsion|occlusion|embolism|thrombus|dissection|pneumothorax|mass effect|midline shift)\b', t))
    cn=any(k in t for k in ['急性','出血','血肿','挫伤','撕裂','外伤','创伤','骨折','缺血','梗死','穿孔','游离气体','破裂','扭转','闭塞','栓塞','血栓','夹层','气胸','占位效应','中线移位','纵隔移位'])
    return en or cn


def high_impact_abnormal_text(text):
    """Disease-agnostic high-impact signals that can justify A1 or preserve a strict conflict."""
    t=_norm(text)
    hard_en=bool(re.search(r'\b(mass|tumou?r|malignan|cancer|metasta|invasion|invasive|spiculated|lobulated|acute|severe|marked|large|embolism|embolic|emboli|embolus|thrombus|thrombosis|filling defect|vascular occlusion|arterial occlusion|occlusion|dissection|hemorrhage|bleeding|hematoma|perforation|free air|rupture|obstruction|ischemia|infarct|fracture|pneumothorax|midline shift|mass effect|abscess|empyema)\b', t))
    hard_cn=any(k in t for k in ['肿块','占位','恶性','癌','转移','侵犯','毛刺','分叶','急性','重度','明显','显著','大量','肺栓塞','栓塞','血栓','充盈缺损','血管闭塞','闭塞','夹层','出血','血肿','穿孔','游离气体','破裂','梗阻','缺血','梗死','骨折','气胸','中线移位','纵隔移位','占位效应','脓肿','脓胸'])
    if hard_en or hard_cn:
        return True
    extent_en=bool(re.search(r'\b(diffuse|extensive|widespread|multifocal|multilobar|confluent|exudative|interstitial[- ]?alveolar|crazy[- ]?paving|whole|entire)\b', t))
    extent_cn=any(k in t for k in ['弥漫','广泛','多发','多灶','多叶','融合','大片','全肺','双肺','两肺','渗出性','间质肺泡性'])
    minor_en=bool(re.search(r'\b(tiny|small|slight|mild|minimal|trace|few|punctate|linear|band[- ]?like|stripe|streak|old|chronic|dependent|gravity[- ]?dependent|fibrotic|fibrosis|calcified|calcification|degenerative|emphysematous|emphysema|hyperlucency|lucent|bronchiectatic|bronchiectasis|micronodule|micro[- ]?nodule)\b', t))
    minor_cn=any(k in t for k in ['微小','小','少许','少量','轻度','微量','点状','条索','索条','陈旧','慢性','坠积','纤维','纤维灶','钙化','退变','透亮度增高','肺气肿','肺大泡','支气管扩张','微结节'])
    active_en=bool(re.search(r'\b(consolidat|ground[- ]?glass|opacity|infiltrat|exudative|edema|pneumonia)\b', t))
    active_cn=any(k in t for k in ['实变','磨玻璃','密度影','浸润','渗出','水肿','肺炎','炎症','斑片'])
    return (extent_en or extent_cn) and (active_en or active_cn) and not (minor_en or minor_cn)


def high_risk_positive_axis_text(text):
    """High-risk generated-only positive axes that must not be softened solely for hedging/template wording."""
    t=_norm(text)
    # Hard clinical-impact categories: malignancy/staging, vascular emergencies, acute safety complications,
    # major obstruction/ischemia, substantial infection/consolidation, major fluid, and clinically important fracture.
    hard_en=bool(re.search(r'\b(mass|tumou?r|malignan|cancer|metasta|invasion|invasive|spiculated|lobulated|embolism|embolic|emboli|embolus|thrombus|thrombosis|filling defect|vascular occlusion|arterial occlusion|occlusion|dissection|hemorrhage|bleeding|hematoma|perforation|free air|rupture|ischemia|infarct|pneumothorax|midline shift|mass effect|abscess|empyema)\b', t))
    hard_cn=any(k in t for k in ['肿块','占位','恶性','癌','转移','侵犯','毛刺','分叶','肺栓塞','栓塞','血栓','充盈缺损','血管闭塞','闭塞','夹层','出血','血肿','穿孔','游离气体','破裂','缺血','梗死','气胸','中线移位','纵隔移位','占位效应','脓肿','脓胸'])
    if hard_en or hard_cn:
        return True
    # Severe/definite active disease.  "Bilateral/two lungs" alone is deliberately insufficient;
    # require severity/extent plus active diagnostic direction, so vague menu-like lung phrases can still be softened.
    severe_en=bool(re.search(r'\b(severe|marked|large|extensive|widespread|multilobar|confluent|lobar|complete|acute)\b', t))
    severe_cn=any(k in t for k in ['重度','明显','显著','大量','广泛','弥漫','多叶','多肺叶','融合','大片','全肺','急性'])
    active_en=bool(re.search(r'\b(consolidat|exudative|pneumonia|infectious|infection|collapse|obstruction|high[- ]?grade stenosis)\b', t))
    active_cn=any(k in t for k in ['实变','渗出','肺炎','感染','炎症','肺叶不张','完全不张','梗阻','高度狭窄','严重狭窄','支气管充气征'])
    if (severe_en or severe_cn) and (active_en or active_cn):
        return True
    major_fluid_en=bool(re.search(r'\b(large|moderate|loculated|tension|hemothorax|empyema|infected)\b.*\b(effusion|fluid|ascites)\b', t))
    major_fluid_cn=any(k in t for k in ['大量积液','大量胸腔积液','大量腹水','中等量积液','中量积液','中等量胸腔积液','包裹性积液','张力性积液','血胸'])
    if major_fluid_en or major_fluid_cn:
        return True
    # Fracture is high-risk only when definite/acute/displaced/multiple or otherwise clinically stressed.
    fracture_en=('fracture' in t) and bool(re.search(r'\b(acute|displaced|multiple|several|comminuted|unstable|definite)\b', t))
    fracture_cn=('骨折' in t) and any(k in t for k in ['急性','错位','移位','多发','粉碎','明确','明显','不稳定'])
    return fracture_en or fracture_cn

def low_certainty_text(text):
    """Low-certainty or verification-needed wording. This is only one input to the soft-positive guard."""
    t=_norm(text)
    en=bool(re.search(r'\b(possible|possibly|suspected|suspicious|questionable|indeterminate|cannot exclude|may represent|may be|could represent|suggest|suggesting|recommend correlation|follow[- ]?up|recheck|review)\b', t))
    cn=any(k in t for k in ['可能','疑似','可疑','考虑','提示','不除外','不能除外','待排','待复核','建议复核','建议结合','线索','需结合','证据不足','进一步评估'])
    return en or cn

def template_enumeration_text(text):
    """Model-like menu/list wording: multiple heterogeneous abnormal categories with weak concrete evidence."""
    t=_norm(text)
    # separators commonly used in menu-style generated findings
    sep_count=sum(t.count(x) for x in ['/', '或', '、', ';', '；'])
    groups=0
    category_terms=[
        ['结节','nodule'], ['磨玻璃','ground-glass','ground glass'], ['斑片','patchy'],
        ['实变','consolidat'], ['不张','atelecta','collapse'], ['条索','索条','linear','streak','fibrotic','scar'],
        ['肺气肿','肺大疱','透亮','emphysema','bullous','lucent'], ['淋巴结','lymph node'],
        ['积液','effusion'], ['钙化','calcification','calcified'], ['骨折','fracture']
    ]
    for aliases in category_terms:
        if any(a in t for a in aliases):
            groups+=1
    menu_cue=any(k in t for k in ['筛查提示','可疑','线索','建议复核','建议结合','需结合薄层','散在结节/结节样','斑片或实变/不张','肺气肿/肺大疱'])
    return (sep_count>=2 and groups>=3) or (menu_cue and groups>=2) or ('/' in t and '或' in t and groups>=2)

def low_specificity_positive_text(text):
    """Low-specificity positive abnormality: broad, underspecified, or candidate-style without concrete location/extent/diagnosis."""
    t=_norm(text)
    if not has_positive_abnormal_signal(t):
        return False
    # Concrete measurements, named subregions, strong severity, or a clear diagnostic direction make the assertion specific.
    has_measure=bool(re.search(r'\d+\s*(mm|cm|毫米|厘米|×|x)', t))
    specific_site=bool(re.search(r'\b(right|left|upper|middle|lower|lobe|segment|subsegment|hilum|mediastinal|pleural|rib|aortic|coronary|pulmonary artery)\b', t)) or any(k in t for k in ['右肺','左肺','上叶','中叶','下叶','肺段','亚段','背段','基底段','尖段','前段','后段','内段','外段','肺门','纵隔','胸膜','胸腔','肋','主动脉','冠脉','冠状动脉','肺动脉'])
    severity=bool(re.search(r'\b(severe|marked|large|moderate|extensive|diffuse|widespread|confluent|acute|definite)\b', t)) or any(k in t for k in ['明显','显著','重度','大量','中等量','中量','广泛','弥漫','融合','大片','急性','明确'])
    diagnosis=bool(re.search(r'\b(consistent with|compatible with|diagnosis|malignan|embolism|pneumonia|infection|fracture|dissection|hemorrhage|perforation)\b', t)) or any(k in t for k in ['符合','诊断','恶性','栓塞','肺炎','感染','炎性实变','骨折','夹层','出血','穿孔'])
    # Candidate/menu phrasing can remain low-specificity even with a broad bilateral/mediastinal location unless it has strong severity/diagnosis.
    if template_enumeration_text(t) and not (severity or diagnosis or has_measure):
        return True
    if has_measure or severity or diagnosis:
        return False
    # A merely broad anatomic container (肺内/双肺/两肺/纵隔肺门) without more detail is still low-specificity.
    broad_only_site=any(k in t for k in ['肺内','双肺','两肺','纵隔/肺门','肺门/纵隔']) and not any(k in t for k in ['上叶','中叶','下叶','肺段','亚段','右肺','左肺'])
    vague=any(k in t for k in ['局灶','局部','散在','可疑','线索','若干','部分','或','样','待复核','建议复核','建议结合']) or bool(re.search(r'\b(focal|scattered|possible|suspected|suggested|candidate|like|or)\b', t))
    return (broad_only_site or vague) and not specific_site

def generated_only_soft_positive_guard(text):
    """General non-case-specific soft false-positive guard.
    True only for generated-only positive findings that are low-certainty/template-like, low-specificity,
    and not high-risk. It prevents low-specificity menu-like generated extras from dominating the score.
    """
    t=_norm(text)
    if not has_positive_abnormal_signal(t):
        return False
    if high_risk_positive_axis_text(t):
        return False
    return (low_certainty_text(t) or template_enumeration_text(t)) and low_specificity_positive_text(t)

def low_risk_minor_abnormal_text(text):
    """Low-risk/minor/incidental descriptors should not become A1 merely because they are the most visible abnormality."""
    t=_norm(text)
    minor_en=bool(re.search(r'\b(tiny|small|slight|mild|minimal|trace|few|punctate|linear|band[- ]?like|stripe|streak|scattered|old|chronic|dependent|gravity[- ]?dependent|fibrotic|calcified|calcification|degenerative|simple cyst|steatosis|fatty|nonspecific|non[- ]?specific)\b', t))
    minor_cn=any(k in t for k in ['微小','小','少许','少量','微量','轻度','点状','条索','索条','散在','陈旧','慢性','坠积','纤维','钙化','退变','单纯囊肿','脂肪肝','脂肪浸润','非特异性'])
    return (minor_en or minor_cn) and not high_impact_abnormal_text(t)

def broad_normal_screen_text(text):
    """A catch-all normal screen, not a specific denial of a named safety-critical abnormality."""
    t=_norm(text)
    broad_en=bool(re.search(r'\b(no|without|absent|absence of|not seen|no obvious|no definite|unremarkable|normal)\b', t)) and bool(re.search(r'\b(other|remaining|otherwise|no obvious abnormal|abnormal density|abnormal signal|gross abnormality|significant abnormality|routine screen|screen)\b', t))
    broad_cn=_has_neg_marker(t) and any(k in t for k in ['其他','其余','余','未见明显异常','未见异常密度','未见异常信号','未见明显病变','未见明显占位','大致正常','无明显异常'])
    specific_critical=bool(re.search(r'\b(embolism|embolus|thrombus|hemorrhage|bleeding|perforation|free air|obstruction|ischemia|infarct|fracture|pneumothorax|metastasis|vascular invasion|dissection)\b', t)) or any(k in t for k in ['栓塞','血栓','充盈缺损','出血','穿孔','游离气体','梗阻','缺血','梗死','骨折','气胸','转移','血管侵犯','夹层'])
    return (broad_en or broad_cn) and not specific_critical

def parenchymal_active_process_text(text):
    """Generic active lung parenchymal process vocabulary, separated from nodules/linear scars."""
    t=_norm(text)
    en=bool(re.search(r'\b(consolidat|infiltrat|exudat|pneumonia|infectious|infection|atelecta|collapse|air bronchogram|crazy[- ]?paving|edema)\b', t))
    cn=any(k in t for k in ['实变','浸润','渗出','肺炎','感染','炎性','不张','支气管充气征','铺路石','水肿'])
    return en or cn


def dominant_extent_scale_mismatch(ref_text, gen_text):
    """Detect generic mismatch between a focal/minor process and a diffuse/extensive dominant active process.

    Refinement: bilateral/scattered small nodules or GGNs are not by themselves a dominant-scale
    mismatch. The zero-credit escalation is reserved for a true scale/identity conflict, especially when
    one side is minor/focal/chronic and the other side describes an extensive active process.
    """
    r=_norm(ref_text); g=_norm(gen_text)
    if not (has_positive_abnormal_signal(r) and has_positive_abnormal_signal(g)):
        return False
    severe_extent_en=r'\b(diffuse|extensive|widespread|multifocal|multilobar|confluent|large|mass[- ]?like|whole|entire)\b'
    focal_minor_en=r'\b(solitary|single|focal|localized|local|tiny|small|few|punctate|linear|band[- ]?like|stripe|streak|old|chronic|fibrotic|micronodule|micro[- ]?nodule)\b'
    severe_extent_cn=['弥漫','广泛','多灶','多叶','多肺叶','多肺段','融合','大片','全肺']
    focal_minor_cn=['单发','局灶','局限','微小','小','少许','点状','条索','索条','陈旧','慢性','纤维','微结节']
    nodule_axis=lambda x: any(k in x for k in ['结节','磨玻璃结节','nodule','ground-glass nodule','ground glass nodule'])
    active_r=parenchymal_active_process_text(r)
    active_g=parenchymal_active_process_text(g)
    # Do not convert a merely less-specific but same-axis small nodule/GGN match into core_conflict.
    # Missing size/location remains limited or attribute_conflict, not zero-credit, unless the other side
    # turns it into a clearly extensive active/infiltrative process.
    if nodule_axis(r) and nodule_axis(g) and not (active_r or active_g):
        return False
    r_ext=bool(re.search(severe_extent_en,r)) or any(k in r for k in severe_extent_cn) or (any(k in r for k in ['双肺','两肺','bilateral']) and active_r and not nodule_axis(r))
    g_ext=bool(re.search(severe_extent_en,g)) or any(k in g for k in severe_extent_cn) or (any(k in g for k in ['双肺','两肺','bilateral']) and active_g and not nodule_axis(g))
    r_foc=bool(re.search(focal_minor_en,r)) or any(k in r for k in focal_minor_cn) or (nodule_axis(r) and not active_r)
    g_foc=bool(re.search(focal_minor_en,g)) or any(k in g for k in focal_minor_cn) or (nodule_axis(g) and not active_g)
    return ((r_ext and g_foc and not g_ext) or (g_ext and r_foc and not r_ext))


def generated_only_active_parenchymal_soft_text(text):
    """Generated-only active parenchymal abnormalities that are too clinically meaningful for pure A3,
    but may be low-specificity/template-like enough to receive reduced A2 dominance rather than full A2 dominance.
    This is generic and intentionally not tied to any case ID or exact sentence.
    """
    t=_norm(text)
    if not has_positive_abnormal_signal(t):
        return False
    if high_risk_positive_axis_text(t):
        return False
    return parenchymal_active_process_text(t) and (low_certainty_text(t) or template_enumeration_text(t) or low_specificity_positive_text(t))


def unilateral_low_tier_positive_abnormal(c):
    """Generic low-tier omission/addition cap: positive incidental/local abnormalities should prevent near-perfect scores."""
    if c.get('concept_type')=='matched': return False
    t=_norm(' '.join([str(c.get('clinical_concept','')),str(c.get('ref_sentence','')),str(c.get('gen_sentence',''))]))
    if _has_neg_marker(t) and not has_positive_abnormal_signal(t):
        return False
    return c.get('concept_axis') in {'incidental_abnormality','fluid_or_obstruction_or_vascular_or_complication','local_effect'} or c.get('tier')=='A3'

def likely_history_only_sru(u):
    txt=' '.join([str(u.get('sentence','')),str(u.get('core_assertion','')),str(u.get('merge_rationale',''))]).lower()
    history_markers=['history of','known','confirmed','diagnosed','follow-up','follow up','recheck','surveillance','post treatment','postoperative follow-up']+CN_HISTORY_MARKERS
    imaging_markers=['seen','shows','demonstrates','there is','there are','lesion','mass','nodule','opacity','effusion','thickening','enlarged','dilatation','enhancement','density','signal']+CN_IMAGING_MARKERS
    return any(m in txt for m in history_markers) and not any(m in txt for m in imaging_markers)

def mixed_polarity_ids(row, c):
    ref_kind={u['id']:u.get('unit_kind','') for u in row.get('_ref_srus',[])}
    gen_kind={u['id']:u.get('unit_kind','') for u in row.get('_gen_srus',[])}
    kinds=[ref_kind.get(x,'') for x in c.get('ref_ids',[])] + [gen_kind.get(x,'') for x in c.get('gen_ids',[])]
    return ('independent_assertion' in kinds) and ('normal_negative' in kinds)

def validate_joint(ref_row,gen_row,obj):
    ref_ids={u['id'] for u in ref_row.get('semantic_units',[])}; gen_ids={u['id'] for u in gen_row.get('semantic_units',[])}
    seen_r=[]; seen_g=[]; out=[]; raw=obj.get('shared_concepts')
    if not isinstance(raw,list): raise ValueError('shared_concepts must be list')
    for i,c in enumerate(raw,1):
        if not isinstance(c,dict): raise ValueError('concept item must be object')
        rid=[str(x) for x in (c.get('ref_ids') or [])]; gid=[str(x) for x in (c.get('gen_ids') or [])]
        rid=[x for x in dict.fromkeys(rid) if x in ref_ids]; gid=[x for x in dict.fromkeys(gid) if x in gen_ids]
        if rid and gid: ctype='matched'
        elif rid: ctype='reference_only'
        elif gid: ctype='generated_only'
        else: continue
        q=c.get('match_quality') if c.get('match_quality') in VALID_QUALITY else ('limited' if ctype=='matched' else 'none')
        if ctype!='matched': q='none'
        elif q=='none': q='limited'
        tier=c.get('tier') if c.get('tier') in VALID_TIERS else 'A2'
        anat=c.get('anatomical_relationship') if c.get('anatomical_relationship') in VALID_REL else (None if ctype!='matched' else 'equivalent')
        det=c.get('details_relationship') if c.get('details_relationship') in VALID_DETAILS else (None if ctype!='matched' else 'absent')
        same_axis=parse_bool_or_none(c.get('same_axis_contradiction'))
        guard_adjustment=''
        # Deterministic guard: core_conflict is allowed only when the prompt explicitly confirms same-axis contradiction.
        # If not confirmed, downgrade to limited to avoid unstable over-penalization from mixing related-but-different axes.
        if ctype=='matched' and q=='core_conflict' and same_axis is not True:
            q='limited'
            if det=='conflicting': det='partial'
            guard_adjustment='core_conflict_downgraded_without_same_axis_confirmation'
        axis=str(c.get('concept_axis') or 'other')
        if axis not in {'dominant_lesion','local_effect','nodal_disease','serosal_or_pleural_or_peritoneal','fluid_or_obstruction_or_vascular_or_complication','incidental_abnormality','normal_negative','technical_or_quality','other'}:
            axis='other'
        parent_id=c.get('parent_concept_id')
        parent_id=str(parent_id) if parent_id not in [None,'', 'null'] else None
        ref_text=str(c.get('ref_sentence',''))
        gen_text=str(c.get('gen_sentence',''))
        concept_text=' '.join([str(c.get('clinical_concept','')),ref_text,gen_text,str(c.get('brief_rationale','')),str(c.get('boundary_rationale','')),str(c.get('tier_rationale',''))]).lower()
        # Generalized stability guard: do not give partial A1 credit simply because a broad
        # catch-all normal screen was paired with a generated/ref positive dominant abnormality.
        # A specific negative (e.g. explicit denial of a safety-critical condition) may still be
        # a true same-axis conflict; a generic "no other abnormality" screen is treated as zero-credit conflict.
        if ctype=='matched' and q=='core_conflict' and ((broad_normal_screen_text(ref_text) and has_positive_abnormal_signal(gen_text)) or (broad_normal_screen_text(gen_text) and has_positive_abnormal_signal(ref_text))):
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'broad_normal_screen_positive_conflict_zero_credit'
        # Generalized scale guard: focal/minor chronic or nodule-like findings are not the same
        # dominant clinical process as diffuse/extensive acute/exudative/multifocal disease merely
        # because both use generic opacity/nodule words.
        if ctype=='matched' and axis=='dominant_lesion' and dominant_extent_scale_mismatch(ref_text, gen_text):
            if q in {'full','substantial','attribute_conflict'}:
                q='core_conflict'
            det='conflicting'; same_axis=True
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'dominant_extent_scale_mismatch_zero_credit'
        # Generalized tier guard: low-risk/minor/incidental abnormality should not become A1
        # merely because it is the most prominent available abnormality in a low-acuity report.
        if tier=='A1' and axis in {'dominant_lesion','incidental_abnormality','local_effect'} and low_risk_minor_abnormal_text(concept_text):
            tier='A2'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'low_risk_minor_A1_demoted_to_A2'
        hedge=bool(re.search(r'\b(possible|possibly|suspected|suspicious|suggest|suggesting|unclear|indistinct|questionable|cannot exclude|may represent|abutment|abutting)\b', concept_text)) or any(k in concept_text for k in ['可能','疑似','考虑','提示','不除外','不能除外','欠清','模糊','可疑','邻近','贴近','关系密切'])
        dependent_axis=axis in {'local_effect','fluid_or_obstruction_or_vascular_or_complication'}
        critical_dep=critical_dependent_phrase(concept_text)
        # V3: unilateral dependent local/fluid details of an already recognized parent should not destabilize A1/A2.
        # Keep A2 only when generic wording indicates independent staging/safety/management relevance.
        if ctype=='generated_only' and tier in {'A1','A2'} and dependent_axis and (hedge or not critical_dep):
            tier='A3'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'generated_only_nondecisive_dependent_downgraded_to_A3'
        elif ctype=='generated_only' and tier=='A1' and dependent_axis:
            tier='A2'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'generated_only_critical_dependent_A1_downgraded_to_A2'
        # V2 low-specificity soft-positive guard: only for generated-only, non-high-risk,
        # template/candidate-like positive abnormalities with low specificity. This reduces false-low
        # scores from menu-like model extras without weakening definite/high-risk false positives.
        soft_positive_text=' '.join([str(c.get('clinical_concept','')), gen_text])
        if ctype=='generated_only' and tier in {'A1','A2'} and generated_only_soft_positive_guard(soft_positive_text):
            if tier=='A1':
                tier='A2'
                guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'generated_only_low_specificity_template_noncritical_A1_demoted_to_A2'
            elif tier=='A2':
                # Keep the A2 label so the extra abnormality is still penalized, but mark it for
                # reduced dominance if it is the only high-tier abnormality. This avoids both
                # near-zero false-low scores and overgenerous A2->A3 release.
                guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'generated_only_low_specificity_template_noncritical_A2_soft_dominance'
        if ctype=='generated_only' and tier=='A3' and generated_only_active_parenchymal_soft_text(str(c.get('clinical_concept',''))):
            tier='A2'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'generated_only_active_parenchymal_A3_promoted_to_A2_soft_dominance'
        if tier=='A1' and axis in {'technical_or_quality'}:
            tier='A3'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'technical_A1_downgraded_to_A3'
        # Normal-negative guard: absence statements should not become A1. Critical negatives may be A2
        # only when explicitly process-specific; routine/broad negatives remain N. This prevents normal screens
        # from dominating the report score while still allowing important exclusions to be tracked.
        neg_only_pre=_has_neg_marker(concept_text) and not has_positive_abnormal_signal(concept_text)
        critical_neg_pre=bool(re.search(r'\b(no|without|absent|absence of|not seen|no obvious|no definite)\b.*\b(metastasis|embolism|embolus|emboli|thrombus|filling defect|hemorrhage|bleeding|free air|perforation|ischemia|obstruction|vascular invasion|dissection|pneumothorax)\b', concept_text)) or (_has_neg_marker(concept_text) and any(k in concept_text for k in ['转移','栓塞','血栓','充盈缺损','出血','游离气体','穿孔','缺血','梗阻','血管侵犯','夹层','气胸']))
        if axis=='normal_negative' and tier=='A1':
            tier='A2' if critical_neg_pre else 'N'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'normal_negative_A1_demoted'
        if axis=='normal_negative' and tier=='A2' and not critical_neg_pre:
            tier='N'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'routine_normal_negative_A2_demoted_to_N'
        neg_only=neg_only_pre
        critical_neg=bool(re.search(r'\b(no|without|absent|absence of|not seen|no obvious|no definite)\b.*\b(metastasis|embolism|embolus|emboli|thrombus|filling defect|hemorrhage|bleeding|free air|perforation|ischemia|obstruction|vascular invasion|dissection|pneumothorax)\b', concept_text)) or (_has_neg_marker(concept_text) and any(k in concept_text for k in ['转移','栓塞','血栓','充盈缺损','出血','游离气体','穿孔','缺血','梗阻','血管侵犯','夹层','气胸']))
        if ctype!='matched' and neg_only and not critical_neg and tier!='N':
            tier='N'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'unilateral_noncritical_negative_downgraded_to_N'
        low_sig=bool(re.search(r'\b(mild|slight|small|trace|minimal|tiny|suboptimal|poor disten|calcification|calcified|steatosis|fatty|simple cyst|cystic|degenerative)\b', concept_text)) or any(k in concept_text for k in ['轻度','少许','少量','微量','微小','小','欠佳','充盈欠佳','钙化','脂肪肝','脂肪浸润','单纯囊肿','囊肿','退变','陈旧'])
        if tier=='A2' and axis in {'incidental_abnormality','technical_or_quality'} and low_sig:
            tier='A3'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'low_significance_A2_downgraded_to_A3'
        if tier=='A2' and axis in {'local_effect','fluid_or_obstruction_or_vascular_or_complication'} and not critical_dep:
            tier='A3'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'nondecisive_local_or_fluid_A2_downgraded_to_A3'
            if ctype=='matched' and q=='core_conflict':
                q='limited'; det='partial'
                guard_adjustment += ';noncritical_local_core_conflict_softened'
        if tier=='A2' and low_volume_or_unspecified_fluid(concept_text) and not critical_dep:
            tier='A3'
            guard_adjustment=(guard_adjustment+';' if guard_adjustment else '')+'low_volume_or_unspecified_fluid_A2_downgraded_to_A3'
        seen_r.extend(rid); seen_g.extend(gid)
        out.append({'concept_id':str(c.get('concept_id') or f'C{i:03d}'),'tier':tier,'concept_axis':axis,'concept_type':ctype,'ref_ids':rid,'gen_ids':gid,'ref_sentence':str(c.get('ref_sentence','')),'gen_sentence':str(c.get('gen_sentence','')),'clinical_concept':str(c.get('clinical_concept','')),'match_quality':q,'same_axis_contradiction':same_axis,'anatomical_relationship':anat,'details_relationship':det,'parent_concept_id':parent_id,'boundary_rationale':str(c.get('boundary_rationale','')),'tier_rationale':str(c.get('tier_rationale','')),'brief_rationale':str(c.get('brief_rationale','')),'guard_adjustment':guard_adjustment})
    # V8 generic nodal hierarchy guard (not disease-specific):
    # - If a dominant lesion/process exists, nodal status is usually an independent staging/prognostic axis, but not the dominant A1 process itself.
    # - Clearly abnormal/suspicious unilateral nodal findings should not be collapsed into N by generic negative-text heuristics.
    # - Merely small/nonspecific nodes are not promoted.
    has_dominant_a1=any(cc.get('tier')=='A1' and cc.get('concept_axis')=='dominant_lesion' for cc in out)
    for cc in out:
        if cc.get('concept_axis')=='nodal_disease' and cc.get('tier')=='A1' and has_dominant_a1:
            cc['tier']='A2'
            cc['guard_adjustment']=(cc.get('guard_adjustment','')+';' if cc.get('guard_adjustment') else '')+'nodal_axis_A1_demoted_to_A2_when_dominant_lesion_exists'
        if cc.get('concept_axis')=='nodal_disease' and cc.get('concept_type')!='matched' and cc.get('tier') in {'N','A3'} and positive_nodal_concept(cc.get('clinical_concept','')):
            cc['tier']='A2'
            cc['guard_adjustment']=(cc.get('guard_adjustment','')+';' if cc.get('guard_adjustment') else '')+'unilateral_positive_nodal_axis_promoted_to_A2'
    # V11 generic double-penalty guard:
    # If a separate complication/local-effect concept already captures a core conflict, do not also
    # penalize the parent dominant disease as attribute_conflict unless the parent itself is a same-axis contradiction.
    has_complication_core_conflict=any(cc.get('tier') in {'A1','A2'} and cc.get('concept_axis') in {'fluid_or_obstruction_or_vascular_or_complication','local_effect'} and cc.get('match_quality')=='core_conflict' for cc in out)
    if has_complication_core_conflict:
        for cc in out:
            if cc.get('tier')=='A1' and cc.get('concept_axis')=='dominant_lesion' and cc.get('match_quality')=='attribute_conflict' and cc.get('same_axis_contradiction') is not True:
                cc['match_quality']='substantial'
                if cc.get('details_relationship')=='conflicting': cc['details_relationship']='partial'
                cc['guard_adjustment']=(cc.get('guard_adjustment','')+';' if cc.get('guard_adjustment') else '')+'parent_dominant_conflict_softened_because_separate_complication_conflict_exists'
    dup_r={x for x in seen_r if seen_r.count(x)>1}; dup_g={x for x in seen_g if seen_g.count(x)>1}; miss_r=ref_ids-set(seen_r); miss_g=gen_ids-set(seen_g)
    if dup_r or dup_g or miss_r or miss_g: raise ValueError(f'coverage violation dup_r={sorted(dup_r)} dup_g={sorted(dup_g)} miss_r={sorted(miss_r)} miss_g={sorted(miss_g)}')
    meta={k:gen_row.get(k, ref_row.get(k)) for k in ['model','case_id','original_name','repeat_id','selection_reason','category','selection_model_tier','model_original_mean','original_radcise_score','original_guard_warning_count','original_guard_warning_ratio'] if k in gen_row or k in ref_row}
    return {'name':gen_row.get('name', ref_row['name']),'Examined_Area':ref_row.get('Examined_Area',''),'Examined_Type':ref_row.get('Examined_Type',''),'case_summary':str(obj.get('case_summary','')),'shared_concepts':out, **meta}
def concept_credit(c):
    if c['concept_type']!='matched': return 0.0
    if 'zero_credit' in str(c.get('guard_adjustment','')):
        return 0.0
    q=c['match_quality']; credit=QUALITY_CREDIT[q]
    # Avoid double-penalizing attribute_conflict: the quality label already encodes material attribute disagreement.
    if c.get('anatomical_relationship')=='part-whole':
        credit-=0.05 if q in {'substantial','attribute_conflict','limited'} else 0.10
    elif c.get('anatomical_relationship')=='incompatible':
        credit=min(credit,0.25)
    if c.get('details_relationship')=='partial':
        credit-=0.03 if q in {'full','substantial'} else 0.0
    elif c.get('details_relationship')=='conflicting':
        if q=='attribute_conflict':
            credit-=0.0
        elif q=='core_conflict':
            credit-=0.0
        else:
            credit-=0.10
    if q!='core_conflict': credit=max(LOCAL_FLOOR_NON_CORE,credit)
    return max(0,min(1,credit))
def aggregation_weights(counts):
    """Dynamic A1/A2/A3/N weights covering all non-empty tier combinations.
    With A1 present: A1 dominates; A2 capped at 20%; A3+N capped at 5% (N max 2%).
    Without A1: highest existing abnormal tier becomes the main evaluation target.
    """
    tiers=['A1','A2','A3','N']
    counts={t:int(counts.get(t,0)) for t in tiers}
    if sum(counts.values())==0:
        return {t:0 for t in tiers}
    raw={'A1':counts['A1']*1.0,'A2':counts['A2']*0.35,'A3':counts['A3']*0.05,'N':counts['N']*0.005}
    if counts['A1']>0:
        minor_raw=raw['A3']+raw['N']
        total=sum(raw.values())
        minor_share=min(minor_raw/total if total else 0,0.05)
        n_share=0.0
        if minor_raw>0:
            n_share=min(minor_share*(raw['N']/minor_raw),0.02)
        a3_share=max(0.0,minor_share-n_share)
        rem=1.0-minor_share
        major_raw=raw['A1']+raw['A2']
        a2_share=min(rem*(raw['A2']/major_raw) if major_raw else 0,0.20)
        a1_share=1.0-a2_share-a3_share-n_share
        return {'A1':a1_share,'A2':a2_share,'A3':a3_share,'N':n_share}
    if counts['A2']>0:
        minor_raw=raw['A3']+raw['N']; total=raw['A2']+minor_raw
        minor_share=min(minor_raw/total if total else 0,0.10)
        n_share=0.0
        if minor_raw>0:
            n_share=min(minor_share*(raw['N']/minor_raw),0.03)
        a3_share=max(0.0,minor_share-n_share)
        return {'A1':0,'A2':1.0-a3_share-n_share,'A3':a3_share,'N':n_share}
    if counts['A3']>0:
        total=raw['A3']+raw['N']
        n_share=min(raw['N']/total if total else 0,0.10)
        return {'A1':0,'A2':0,'A3':1.0-n_share,'N':n_share}
    return {'A1':0,'A2':0,'A3':0,'N':1.0}

def score_ceiling(row, raw_final, tier_stats):
    """Generic stability ceiling.
    Preserve concept-level weighted F1, then cap only for broad, clinically interpretable situations:
    low-tier positive abnormalities missed/added, unilateral A1/A2 abnormalities, or severe safety-critical conflicts.
    """
    cap=1.0; reasons=[]; concepts=row.get('shared_concepts',[])
    if any(unilateral_low_tier_positive_abnormal(c) for c in concepts):
        cap=min(cap,0.93); reasons.append('unilateral_low_tier_positive_abnormal_cap_0.93')
    if any(c.get('tier')=='A2' and c.get('concept_type')!='matched' for c in concepts):
        cap=min(cap,0.82); reasons.append('unilateral_A2_abnormal_cap_0.82')
    if any(c.get('tier')=='A1' and c.get('concept_type')!='matched' for c in concepts):
        cap=min(cap,0.65); reasons.append('unilateral_A1_abnormal_cap_0.65')
    a1_core=sum(1 for c in concepts if c.get('tier')=='A1' and c.get('match_quality')=='core_conflict')
    a1_safety_attr=sum(1 for c in concepts if c.get('tier')=='A1' and c.get('match_quality')=='attribute_conflict' and c.get('details_relationship')=='conflicting' and safety_critical_conflict_text(' '.join([str(c.get('clinical_concept','')),str(c.get('ref_sentence','')),str(c.get('gen_sentence','')),str(c.get('brief_rationale',''))])))
    a2_core_safety=sum(1 for c in concepts if c.get('tier')=='A2' and c.get('match_quality')=='core_conflict' and safety_critical_conflict_text(' '.join([str(c.get('clinical_concept','')),str(c.get('ref_sentence','')),str(c.get('gen_sentence','')),str(c.get('brief_rationale',''))])))
    if a1_core>=1 or a1_safety_attr>=2 or a2_core_safety>=2 or (a1_safety_attr>=1 and a2_core_safety>=1):
        cap=min(cap,0.60); reasons.append('severe_or_multiple_safety_critical_conflict_cap_0.60')
    elif a1_safety_attr>=1 or a2_core_safety>=1:
        cap=min(cap,0.78); reasons.append('single_safety_critical_conflict_cap_0.78')
    return min(raw_final,cap), {'applied': raw_final>cap, 'cap': cap, 'reasons': reasons, 'raw_final_before_cap': raw_final}

def score_joint(row):
    concepts=row['shared_concepts']; tiers=['A1','A2','A3','N']; counts={t:sum(1 for c in concepts if c['tier']==t) for t in tiers}; tier_stats={}
    for tier in tiers:
        cs=[c for c in concepts if c['tier']==tier]
        tp=sum(concept_credit(c) for c in cs if c['concept_type']=='matched'); fn=sum(1.0 for c in cs if c['concept_type']=='reference_only'); fp=sum(1.0 for c in cs if c['concept_type']=='generated_only'); residual=sum(1.0-concept_credit(c) for c in cs if c['concept_type']=='matched')
        denom=2*tp+fn+fp+2*residual; f1=1.0 if not cs else (2*tp/denom if denom>0 else 0.0)
        tier_stats[tier]={'concept_count':len(cs),'matched_count':sum(1 for c in cs if c['concept_type']=='matched'),'reference_only_count':sum(1 for c in cs if c['concept_type']=='reference_only'),'generated_only_count':sum(1 for c in cs if c['concept_type']=='generated_only'),'tp_credit':tp,'residual_error_mass':residual,'score':max(0,min(1,f1))}
    w=aggregation_weights(counts)
    # V2 soft-dominance adjustment: when the only A2 concepts are generated-only low-specificity
    # template/candidate positives, keep A2 penalty substantial but do not let that single soft
    # false-positive class consume ~90% of the total score in otherwise low-risk reports.
    a2_concepts=[c for c in concepts if c['tier']=='A2']
    soft_a2_only=(counts['A1']==0 and a2_concepts and all(c.get('concept_type')=='generated_only' and any(flag in c.get('guard_adjustment','') for flag in ['generated_only_low_specificity_template_noncritical_A2_soft_dominance','generated_only_active_parenchymal_A3_promoted_to_A2_soft_dominance']) for c in a2_concepts))
    if soft_a2_only and (counts['A3']>0 or counts['N']>0):
        old_w=dict(w)
        minor_raw=0.15*counts.get('A3',0)+0.05*counts.get('N',0)
        n_share=0.0
        if minor_raw>0:
            n_share=min(0.55*(0.05*counts.get('N',0)/minor_raw),0.03)
        a3_share=0.55-n_share
        w={'A1':0,'A2':0.45,'A3':max(0.0,a3_share),'N':max(0.0,n_share)}
        for c in a2_concepts:
            c['guard_adjustment']=(c.get('guard_adjustment','')+';' if c.get('guard_adjustment') else '')+'soft_generated_only_A2_reduced_dominance_weight'
    raw_final=sum(w[t]*tier_stats[t]['score'] for t in tiers)
    final,cap_info=score_ceiling(row,max(0,min(1,raw_final)),tier_stats)
    return {'name':row['name'],'radcise_score':max(0,min(1,final)),'raw_score_before_ceiling':max(0,min(1,raw_final)),'score_ceiling':cap_info,'tier_scores':{t:tier_stats[t]['score'] for t in tiers},'aggregation_weights':w,'shared_tier_counts':counts,'tier_stats':tier_stats,'scoring_method':'RadCISE-CN_directSRU_clinicalImpact','match_quality_credit':QUALITY_CREDIT,'tier_weight_design':'A1存在时由A1主导；A1存在时A2最高约20%；A3+N最高约5%；无A1时由最高存在异常层级主导；中文医学术语guard；动态四层临床影响加权；确定性双重惩罚、低特异性generated-only阳性guard、A2-soft边界与稳定性上限','non_core_conflict_local_floor':LOCAL_FLOOR_NON_CORE}

def guard_warning_weight(w):
    t=w.get('type','')
    adj=str(w.get('adjustment',''))
    if t=='generated_only_A1_requires_review': return 2.0
    if 'zero_credit' in adj: return 1.5
    if any(k in adj for k in ['A1','core_conflict','critical']): return 1.5
    if t=='guard_adjustment_applied': return 1.0
    if t=='possible_abnormal_labeled_N': return 0.5
    return 1.0

def guard_audit(row):
    warnings=[]; seen_ref=[]; seen_gen=[]
    concepts=row.get('shared_concepts',[])
    for c in concepts:
        seen_ref += c['ref_ids']; seen_gen += c['gen_ids']
        text=(c.get('clinical_concept','')+' '+c.get('ref_sentence','')+' '+c.get('gen_sentence','')).lower()
        if c['tier']=='N' and any(k in text for k in ABNORMAL_KEYWORDS) and not likely_negated_abnormal_phrase(text): warnings.append({'type':'possible_abnormal_labeled_N','concept_id':c['concept_id'],'tier':c['tier'],'clinical_concept':c.get('clinical_concept','')})
        if c['concept_type']=='matched' and c['match_quality']=='none': warnings.append({'type':'matched_with_none_quality','concept_id':c['concept_id']})
        if c['concept_type']!='matched' and c['match_quality']!='none': warnings.append({'type':'unilateral_with_non_none_quality','concept_id':c['concept_id']})
        if c.get('guard_adjustment'): warnings.append({'type':'guard_adjustment_applied','concept_id':c['concept_id'],'adjustment':c.get('guard_adjustment'),'clinical_concept':c.get('clinical_concept','')})
        if c['concept_type']=='generated_only' and c['tier']=='A1': warnings.append({'type':'generated_only_A1_requires_review','concept_id':c['concept_id'],'clinical_concept':c.get('clinical_concept','')})
        if c['match_quality']=='core_conflict' and c.get('same_axis_contradiction') is not True: warnings.append({'type':'possible_core_conflict_overuse','concept_id':c['concept_id'],'clinical_concept':c.get('clinical_concept','')})
    concept_count=len(concepts)
    weighted=sum(guard_warning_weight(w) for w in warnings)
    return {'name':row['name'],'concept_count':concept_count,'warning_count':len(warnings),'warning_ratio':(len(warnings)/concept_count if concept_count else 0),'weighted_warning_count':weighted,'weighted_warning_ratio':(weighted/concept_count if concept_count else 0),'high_risk_warning_count':sum(1 for w in warnings if guard_warning_weight(w)>=1.5),'warnings':warnings}


def normalize_pair_record(row):
    """Normalize one input row into internal reference/generated records."""
    name=str(row.get('name') or row.get('id') or row.get('case_id') or '').strip()
    if not name:
        raise ValueError('Each input row must contain name/id/case_id')
    ref=(row.get('reference_findings') or row.get('reference_report') or row.get('ref_findings') or row.get('ref_report') or row.get('reference') or '').strip()
    gen=(row.get('generated_findings') or row.get('generated_report') or row.get('gen_findings') or row.get('gen_report') or row.get('candidate_findings') or row.get('candidate_report') or row.get('generated') or '').strip()
    if not ref or not gen:
        raise ValueError(f'{name}: missing reference_findings/reference_report or generated_findings/generated_report')
    common={'name':name,'Examined_Area':row.get('Examined_Area') or row.get('examined_area') or row.get('modality_region') or '', 'Examined_Type':row.get('Examined_Type') or row.get('examined_type') or row.get('modality') or ''}
    # Preserve optional metadata for downstream stratified audits; never affects scoring.
    for k in ['model','case_id','original_name','repeat_id','selection_reason','category','selection_model_tier','model_original_mean','original_radcise_score','original_guard_warning_count','original_guard_warning_ratio']:
        if k in row: common[k]=row.get(k)
    return {**common,'English_Report':ref}, {**common,'English_Report':gen}

def load_input_pairs(path):
    rows=read_jsonl(path)
    refs=[]; gens=[]
    for row in rows:
        r,g=normalize_pair_record(row); refs.append(r); gens.append(g)
    return refs, gens

def report_cache_key(record, prefix_id):
    payload=json.dumps({
        'prefix':prefix_id,
        'area':record.get('Examined_Area',''),
        'type':record.get('Examined_Type',''),
        'report':record.get('English_Report','')
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def clone_sru_for_record(base_sru, record):
    cloned=copy.deepcopy(base_sru)
    cloned['name']=record['name']
    cloned['Examined_Area']=record.get('Examined_Area','')
    cloned['Examined_Type']=record.get('Examined_Type','')
    for k in ['model','case_id','original_name','repeat_id','selection_reason','category','selection_model_tier','model_original_mean','original_radcise_score','original_guard_warning_count','original_guard_warning_ratio']:
        if k in record: cloned[k]=record.get(k)
        elif k in cloned: cloned.pop(k,None)
    return cloned

def main(argv=None):
    global ROOT, RUN, OUT, LOG
    parser=argparse.ArgumentParser(description='Run RadCISE-CN: Chinese-localized Radiology Clinical-Impact Semantic Evaluation.')
    parser.add_argument('--input-jsonl', required=True, help='JSONL with name + reference_findings/reference_report + generated_findings/generated_report')
    parser.add_argument('--output-dir', required=True, help='Directory for intermediate outputs and final scores')
    parser.add_argument('--api-key', default=os.environ.get('RADCISE_LLM_API_KEY') or os.environ.get('LLM_API_KEY'), help='LLM API key; recommended to set RADCISE_LLM_API_KEY instead of passing on command line')
    parser.add_argument('--base-url', default=os.environ.get('RADCISE_API_BASE_URL','https://your-llm-provider.example/v1/chat/completions'))
    parser.add_argument('--model', default=os.environ.get('RADCISE_MODEL','YOUR_MODEL_NAME'))
    parser.add_argument('--max-tokens', type=int, default=int(os.environ.get('RADCISE_MAX_TOKENS','16392')))
    parser.add_argument('--timeout-seconds', type=int, default=int(os.environ.get('RADCISE_TIMEOUT_SECONDS','180')))
    parser.add_argument('--max-retries', type=int, default=int(os.environ.get('RADCISE_MAX_RETRIES','5')))
    parser.add_argument('--workers', type=int, default=int(os.environ.get('RADCISE_WORKERS','10')))
    parser.add_argument('--joint-candidates', type=int, default=int(os.environ.get('RADCISE_JOINT_CANDIDATES','3')), help='Number of independent joint-map candidates; median-score candidate is selected')
    args=parser.parse_args(argv)
    if not args.api_key:
        raise SystemExit('Missing API key. Set RADCISE_LLM_API_KEY or pass --api-key.')
    ROOT=Path(__file__).resolve().parents[1]
    RUN=Path(args.output_dir).resolve(); OUT=RUN/'outputs'; LOG=RUN/'run.log'
    RUN.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True); LOG.write_text('',encoding='utf-8')
    ref_rows, gen_rows=load_input_pairs(args.input_jsonl)
    write_jsonl(RUN/'reference_findings.jsonl', ref_rows); write_jsonl(RUN/'generated_findings.jsonl', gen_rows)
    api_cfg={'base_url':args.base_url,'api_key':args.api_key,'model':args.model,'max_tokens':args.max_tokens,'timeout_seconds':args.timeout_seconds,'max_retries':args.max_retries}
    config={'framework':'RadCISE-CN','version':'RadCISE-CN','api':{k:v for k,v in api_cfg.items() if k!='api_key'},'temperature':'omitted','workers':args.workers,'joint_candidates':args.joint_candidates,'llm_api_calls_per_case_design':2+args.joint_candidates,'llm_steps':['金标准 direct-SRU 中文拆解','生成报告 direct-SRU 中文拆解','联合 concept/tier/match 中文判断，并做 self-consistency candidates'],'code_steps':['schema 校验','中文医学术语确定性 guard 审核','动态加权评分','generated-only低特异性/模板式阳性guard']}
    (RUN/'config_no_secret.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    client=Client(api_cfg)
    sru_tpl=(ROOT/'prompts/direct_sru_extraction.txt').read_text(encoding='utf-8')
    joint_tpl=(ROOT/'prompts/joint_concept_tier_match.txt').read_text(encoding='utf-8')
    log(f'START RadCISE-CN; n={len(ref_rows)}; model={args.model}; temperature omitted; workers={args.workers}')
    def direct_one(record,prefix_id):
        base=render(sru_tpl,id_prefix=prefix_id,examined_area=record.get('Examined_Area',''),examined_type=record.get('Examined_Type',''),report=record.get('English_Report',''))
        last=None
        for attempt in range(1,4):
            obj=llm_json(client, base if attempt==1 else base+'\n\nVALIDATION ERROR: '+str(last)+'\nReturn corrected JSON only.', f'{record["name"]}_{prefix_id}_sru_attempt{attempt}')
            try: return validate_sru(record,obj,prefix_id)
            except Exception as e: last=e
        raise last
    def direct_many_cached(rows, prefix_id):
        # General reproducibility guard: identical report text under the same prompt/model is evaluated once
        # and reused within the batch. This is content-addressed caching, not case-specific tuning.
        key_to_first={}
        for r in rows:
            key=report_cache_key(r,prefix_id)
            if key not in key_to_first: key_to_first[key]=r
        unique=list(key_to_first.values())
        log(f'DIRECT SRU {prefix_id}: {len(rows)} rows, {len(unique)} unique report texts after cache de-duplication')
        unique_results=pmap(lambda r: direct_one(r,prefix_id), unique, args.workers)
        cache={report_cache_key(r,prefix_id):res for r,res in zip(unique,unique_results)}
        return [clone_sru_for_record(cache[report_cache_key(r,prefix_id)], r) for r in rows]
    ref_sru=direct_many_cached(ref_rows,'R'); write_jsonl(OUT/'01_reference_direct_sru.jsonl',ref_sru); log('WROTE 01_reference_direct_sru.jsonl')
    gen_sru=direct_many_cached(gen_rows,'G'); write_jsonl(OUT/'02_generated_direct_sru.jsonl',gen_sru); log('WROTE 02_generated_direct_sru.jsonl')
    def joint_one_single(pair, candidate_idx):
        rr,gg=pair
        base=render(joint_tpl,examined_area=rr.get('Examined_Area',''),examined_type=rr.get('Examined_Type',''),reference_srus=fmt_srus(rr),generated_srus=fmt_srus(gg))
        base=base+f'\n\nSELF-CONSISTENCY CANDIDATE {candidate_idx}: Apply the same rules independently. Return JSON only.'
        last=None
        for attempt in range(1,4):
            obj=llm_json(client, base if attempt==1 else base+'\n\nVALIDATION ERROR: '+str(last)+'\nReturn corrected JSON only.', f'{rr["name"]}_joint_c{candidate_idx}_attempt{attempt}')
            try: return validate_joint(rr,gg,obj)
            except Exception as e: last=e
        raise last
    def joint_one(pair):
        candidates=[]
        for k in range(1,args.joint_candidates+1):
            j=joint_one_single(pair,k)
            sc=score_joint(j)['radcise_score']
            j['_self_consistency_candidate_index']=k; j['_self_consistency_score']=sc; candidates.append(j)
        ranked=sorted(candidates,key=lambda x:x['_self_consistency_score'])
        chosen=ranked[len(ranked)//2]
        chosen['_self_consistency_all_scores']=[x['_self_consistency_score'] for x in candidates]
        chosen['_self_consistency_selected']='median_score_candidate'
        return chosen
    joint=pmap(joint_one,list(zip(ref_sru,gen_sru)),args.workers); write_jsonl(OUT/'03_joint_concept_tier_match.jsonl',joint); log('WROTE 03_joint_concept_tier_match.jsonl')
    audit=[{**guard_audit(r), **{k:r.get(k) for k in ['model','case_id','original_name','repeat_id','selection_reason','category','selection_model_tier','model_original_mean','original_radcise_score','original_guard_warning_count','original_guard_warning_ratio'] if k in r}} for r in joint]; write_jsonl(OUT/'04_deterministic_guard_audit.jsonl',audit); log('WROTE 04_deterministic_guard_audit.jsonl')
    scores=[]
    for r in joint:
        s=score_joint(r)
        for k in ['model','case_id','original_name','repeat_id','selection_reason','category','selection_model_tier','model_original_mean','original_radcise_score','original_guard_warning_count','original_guard_warning_ratio']:
            if k in r: s[k]=r.get(k)
        scores.append(s)
    write_jsonl(OUT/'05_scores.jsonl',scores); log('WROTE 05_scores.jsonl')
    vals=[s['radcise_score'] for s in scores]
    summary={'framework':'RadCISE-CN','version':'RadCISE-CN','run_dir':str(RUN),'output_dir':str(OUT),'n':len(vals),'values':vals,'mean':statistics.mean(vals) if vals else None,'median':statistics.median(vals) if vals else None,'min':min(vals) if vals else None,'max':max(vals) if vals else None,'score_rows':scores,'guard_audit_rows':audit,'done_at':time.strftime('%F %T'),'model':args.model,'temperature':'omitted','llm_api_calls_per_case_design':2+args.joint_candidates}
    (RUN/'summary_radcise.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    log('SUMMARY WRITTEN'); log(json.dumps({'scores':[(s['name'],s['radcise_score']) for s in scores],'mean':summary['mean']},ensure_ascii=False))

if __name__=='__main__':
    try:
        main()
    except Exception:
        if LOG:
            log('ERROR\n'+traceback.format_exc())
        raise
