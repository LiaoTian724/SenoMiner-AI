
import os
import time
import sqlite3
import re
import requests
import json
from typing import Optional
from metapub import PubMedFetcher
import pubchempy as pcp

from ai_miner.llm_client import call_doubao_json
from ai_miner.prompts import FIRST_STAGE_PROMPT, SECOND_STAGE_PROMPT, AMBIGUOUS_CHEMICAL_REVIEW_PROMPT
from ai_miner.db_manager import insert_custom_compound
from backend.pipelines.logger import log_print
import datetime
AI_BATCH_LIMIT = 100
AI_TASK_SLEEP = 2.0

def fetch_pubchem_properties(compound_name: str) -> dict:
    props = {
        "cas_number": "N/A", "smiles": "N/A", "inchikey": "N/A", "drug_likeness": "N/A",
        "chembl_id": "N/A", "drugbank_id": "N/A", "common_names": ""
    }
    if not compound_name or compound_name.upper() in ["UNKNOWN", "N/A", "NONE"]:
        return props
    try:
        clean_name = re.sub(r'\s*\([^)]*\)', '', compound_name).strip()
        clean_name = re.sub(r'(?i)\b(extract|formulation|inhibitor)\b', '', clean_name).strip() or compound_name
        
        results = []
        try:
            results = pcp.get_compounds(clean_name, 'name')
        except Exception:
            pass
            
        if not results and clean_name != compound_name:
            try:
                results = pcp.get_compounds(compound_name, 'name')
            except Exception:
                pass

        if results:
            c = results[0]
            props["smiles"] = c.isomeric_smiles or c.canonical_smiles or "N/A"
            props["inchikey"] = c.inchikey or "N/A"
            props["common_names"] = ", ".join(c.synonyms[:5]) if c.synonyms else ""
            props["drug_likeness"] = f"MW: {c.molecular_weight} | XLogP: {c.xlogp}" if c.molecular_weight else "N/A"
            for s in c.synonyms[:60]:
                if re.match(r'^\d{2,7}-\d{2}-\d$', s):
                    props["cas_number"] = s
                    break
        return props
    except:
        return props

def verify_chemical_via_ai_funnel(compound_name: str, context_snippet: str = "") -> bool:
    n = compound_name.strip()
    if len(n) < 2 or n.isdigit() or n.startswith("-") or n.endswith("-"):
        return False
    try:
        r = call_doubao_json(f"Evaluate: {n}", AMBIGUOUS_CHEMICAL_REVIEW_PROMPT.format(compound_name=n, context_snippet=context_snippet[:400]))
        return r.get("is_explicit_junk_fragment") != "YES"
    except:
        return True

def check_real_open_access_via_ncbi(pmid: str) -> bool:
    try:
        return "pmc" in requests.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/eslink.fcgi?db=pubmed&id={pmid}", timeout=8).text.lower()
    except:
        return False


def batch_ai_process(db_path: str, target_specific_pmid: Optional[str] = None):
    db_abs = os.path.abspath(db_path)
    log_print("=" * 70)
    log_print(f"清洗模式：{'单篇PMID' if target_specific_pmid else '批量'} | 库：{db_abs}")
    log_print("=" * 70)

    conn = sqlite3.connect(db_abs, timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if target_specific_pmid:
        cur.execute("SELECT pmid, title, abstract FROM articles WHERE pmid = ?", (str(target_specific_pmid),))
    else:
        cur.execute("SELECT pmid, title, abstract FROM articles WHERE status=0 LIMIT ?", (AI_BATCH_LIMIT,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        log_print("无待处理文献")
        return

    fetcher = PubMedFetcher()

    for row in rows:
        pmid = str(row["pmid"])
        title = row["title"]
        abstract = row["abstract"]
        log_print(f"\n处理 PMID: {pmid} | {title[:50]}...")

        is_oa = check_real_open_access_via_ncbi(pmid)
        oa_val = 1 if is_oa else 0
        pmc, doi, pub_date = None, "N/A", "N/A"

        try:
            art = fetcher.article_by_pmid(pmid)
            pmc = art.pmc
            doi = art.doi or "N/A"
            pub_date = "N/A"
            if art.history and "pubmed" in art.history:
                pub_val = art.history["pubmed"]
                if isinstance(pub_val, (list, tuple)) and pub_val:
                    pub_date = pub_val[0].strftime("%Y-%m-%d")
                elif isinstance(pub_val, datetime.datetime):
                    pub_date = pub_val.strftime("%Y-%m-%d")
        except Exception as e:
            log_print(f"PubMed信息获取失败: {e}")

        first = call_doubao_json(f"Title: {title}\nAbstract: {abstract}", FIRST_STAGE_PROMPT)
        if not first or first.get("is_target_senolytic_paper") != "YES":
            log_print("非目标文献，跳过")
            # 同步更新状态为非目标
            conn = sqlite3.connect(db_abs, timeout=30)
            conn.execute("UPDATE articles SET status=1, reason='一阶初筛未通过' WHERE pmid=?", (pmid,))
            conn.commit()
            conn.close()
            continue

        log_print("目标文献 → 开始提取化合物")
        second = call_doubao_json(f"Title: {title}\nAbstract: {abstract}", SECOND_STAGE_PROMPT)
        print("---大模型返回原始数据---：", second)  
        if not second:
            log_print("未提取到化合物")
            continue

        compounds = second if isinstance(second, list) else [second]

        inserted = []
        for item in compounds:
            if not isinstance(item, dict):
                continue
            raw = item.get("compound_name")
            if not raw:
                continue

            # 分子清洗逻辑
            c_clean = re.sub(r'[\(\)\[\]]', ',', raw)
            c_clean = re.sub(r'(?i)\b(senolytics|senolytic|combination|cocktail|treatment|group|dose|agent|compound|extract|small molecule|inhibitor)\b', '', c_clean).strip()
            parts = [p.strip() for p in re.split(r'[,;，；、]|\band\b', c_clean)]

            for part in parts:
                if len(part) < 2 or len(part) > 50:
                    continue
                if part.lower() in [x.lower() for x in inserted]:
                    continue

                log_print(f"处理分子：{part}")
                pc = fetch_pubchem_properties(part)

                # ================= 调试输出 =================
                smiles_val = pc.get("smiles")
                no_smiles = (smiles_val is None or smiles_val == "N/A")
                ai_ok = verify_chemical_via_ai_funnel(part, abstract)

                log_print(f"分子={part}, no_smiles={no_smiles}, smiles='{smiles_val}', AI验证通过={ai_ok}")
                # ============================================

                if no_smiles and not ai_ok:
                    log_print(f"分子 {part} 被过滤 → 原因：无SMILES + AI判定无效")
                    continue

                # 别名收拢
                aliases = set()
                if item.get("common_names"):
                    aliases.update([a.strip() for a in re.split(r'[,;，；、]', str(item["common_names"]))])
                if pc.get("common_names"):
                    aliases.update([a.strip() for a in pc["common_names"].split(",")])
                final_ali = ", ".join(list(aliases)[:5]) or "N/A"

                payload = {
                    "pmid": pmid,
                    "compound_name": part,
                    "common_names": final_ali,
                    "cas_number": pc.get("cas_number", "N/A"),
                    "doi": doi,
                    "pub_date": pub_date,
                    "pmc_id": pmc,
                    "is_open_access": oa_val,
                    "description": item.get("description", ""),
                    "indications": item.get("indications", ""),
                    "hypotheses_summary": item.get("hypotheses_summary", ""),
                    "in_vitro_data": item.get("in_vitro_data", ""),
                    "in_vivo_data": item.get("in_vivo_data", ""),
                    "in_vitro_anchor": "",
                    "in_vivo_anchor": "",
                    "smiles": pc.get("smiles", "N/A"),
                    "inchikey": pc.get("inchikey", "N/A"),
                    "drug_likeness": pc.get("drug_likeness", "N/A"),
                    "chembl_id": pc.get("chembl_id", "N/A"),
                    "drugbank_id": pc.get("drugbank_id", "N/A")
                }

                try:
                    insert_custom_compound(payload, db_path=db_abs)
                    inserted.append(part)
                except Exception as e:
                    log_print(f"入库失败：{e}")

        # 所有分子遍历清洗并入库结束后，刷新文献状态
        conn = sqlite3.connect(db_abs, timeout=30)
        final_status = 3 if is_oa else (2 if inserted else 1)
        conn.execute("""UPDATE articles SET status=?, compound_count=?, pmc_id=?, is_open_access=? WHERE pmid=?""",
                     (final_status, len(inserted), pmc, oa_val, pmid))
        conn.commit()
        conn.close()
        log_print(f"完成！洗入 {len(inserted)} 个化合物 | status={final_status}")

        if not target_specific_pmid:
            time.sleep(AI_TASK_SLEEP)

    log_print("\n 执行完毕！")