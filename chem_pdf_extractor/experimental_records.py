"""One source-bound database record per independent experiment, not endpoint."""
from __future__ import annotations

import csv
import hashlib
import io
import unicodedata

from .security import sanitize_spreadsheet_cell
from .text_safety import utf8_safe_text

EFFECT_LABELS = {'senolytic':'Senolytic（衰老细胞清除）', 'senomorphic':'Senomorphic（衰老表型调节）',
                 'lifespan':'寿命延长', 'aging_function':'衰老相关功能改善'}
STUDY_LABELS = {'in_vitro':'细胞实验', 'ex_vivo':'离体组织实验', 'in_vivo':'动物实验', 'clinical':'人体给药研究'}
FIELDS = ('model','induction','induction_agent','induction_conditions','recovery','dose','duration','route','control','sample_size','assay')


def paper_records(paper: dict, name: str, identity: dict) -> list[dict]:
    lead = paper.get('lead_claim') or {}
    effect = (paper.get('claim_review') or {}).get('scope','')
    components = identity.get('components') or [identity]
    cids = list(dict.fromkeys(str(p['cid']) for p in components if str(p.get('cid','')).isdigit()))
    records = []
    for group in paper.get('groups',[]):
        # A paper-level reading summary belongs only to its matched cohort.
        story = lead if group['id'] == lead.get('group_id') else group.get('story',{})
        values = {key: str(story.get(key) or group.get(key) or '') for key in FIELDS}
        evidence = {**(group.get('protocol_evidence') or {}), **(story.get('display_evidence') or {})}
        primary = group['id'] == lead.get('group_id')
        key = '\n'.join([str(paper['id']),str(group['id'])])
        records.append({
            'id':'record-'+hashlib.sha256(key.encode()).hexdigest()[:20],
            'compound_name':name, 'pubchem_cids':cids, 'group_id':group['id'],
            'title':group.get('title',''), 'primary':primary,
            'study_type':group.get('study_type',''), 'study_label':STUDY_LABELS.get(group.get('study_type'),'未提取'),
            'effect_type':effect, 'effect_label':EFFECT_LABELS.get(effect,'未提取'),
            **values,
            'result':str(story.get('result') or ''), 'conclusion':str(story.get('scope') or ''),
            'evidence_quote':str(story.get('quote') or group.get('source_claim') or ''),
            'evidence_location':str(story.get('location') or group.get('source_location') or ''),
            'field_evidence':evidence,
            'outcomes':[dict(outcome) for outcome in group.get('outcomes',[])],
            'steps':[dict(step) for step in group.get('steps',[])],
            'source':{key:paper.get(key,'') for key in ('id','title','pmid','doi','year','source_name','url','read_at')},
        })
    # Stable ties preserve the original independent experiments within this paper.
    return sorted(records,key=lambda record:not record['primary'])


def all_records(data: dict) -> list[dict]:
    return [record for compound in data.get('compounds',[]) for paper in compound.get('papers',[])
            for record in paper.get('experiment_records',[])]


CSV_FIELDS = [('compound_name','化合物'),('pubchem_cids','PubChem CID'),('study_label','实验类型'),
              ('effect_label','论文报告作用类型'),('model','研究对象'),('induction_agent','衰老诱导剂'),
              ('induction_conditions','诱导条件'),('induction','造模或预处理原文'),('recovery','恢复培养'),
              ('dose','活性药物浓度或剂量'),('duration','处理时间'),('route','给药方式'),('control','对照'),
              ('sample_size','样本量'),('assay','检测方法'),('result','实验结果'),('conclusion','结论适用范围'),
              ('evidence_quote','效果原文'),('evidence_location','原文位置'),
              ('additional_outcomes','其他检测结果原文'),('procedure','实验操作原文'),
              ('paper_title','来源文献'),('pmid','PMID'),('doi','DOI'),('year','发表年份'),('source_name','来源文件'),('id','实验记录ID')]


def records_csv(records: list[dict]) -> bytes:
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow([label for _,label in CSV_FIELDS])
    for record in records:
        flat = {**(record.get('source') or {}),**record,'paper_title':(record.get('source') or {}).get('title','')}
        flat['pubchem_cids'] = '; '.join(record.get('pubchem_cids',[]))
        flat['additional_outcomes'] = '\n'.join(dict.fromkeys(o.get('quote','') for o in record.get('outcomes',[]) if o.get('quote') != record.get('evidence_quote')))
        flat['procedure'] = '\n'.join(step.get('action','') for step in record.get('steps',[]))
        writer.writerow([sanitize_spreadsheet_cell(utf8_safe_text(str(flat.get(key) or ''))) for key,_ in CSV_FIELDS])
    return stream.getvalue().encode('utf-8-sig')


def filter_records(records: list[dict], query: str = '', study_type: str = '', effect_type: str = '') -> list[dict]:
    """All query conditions must match the same experiment, never mixed cohorts."""
    if study_type and study_type not in STUDY_LABELS:
        raise ValueError('无效实验类型')
    if effect_type and effect_type not in EFFECT_LABELS:
        raise ValueError('无效作用类型')
    words = unicodedata.normalize('NFKC',str(query)[:200]).casefold().split()
    selected = []
    for record in records:
        if study_type and record.get('study_type') != study_type:
            continue
        if effect_type and record.get('effect_type') != effect_type:
            continue
        source = record.get('source') or {}
        haystack = ' '.join(str(record.get(key) or '') for key in ('compound_name','result','study_label','effect_label',*FIELDS))
        haystack += ' ' + ' '.join(str(source.get(key) or '') for key in ('title','pmid','doi'))
        if all(word in unicodedata.normalize('NFKC',haystack).casefold() for word in words):
            selected.append(record)
    return selected
