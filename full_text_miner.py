# backend/pipelines/full_text_miner.py

import os
import time
import random
import sqlite3
import re
import xml.etree.ElementTree as ET
import pandas as pd
import requests
from lxml import etree
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import json

import metapub
from metapub import PubMedFetcher

from ai_miner.db_manager import DB_PATH, init_db
from ai_miner.llm_client import call_doubao_json
from ai_miner.prompts import SECOND_STAGE_PROMPT, THIRD_STAGE_FULL_TEXT_PROMPT
from ai_miner.anchor_calibrator import generate_safe_text_anchor
from backend.pipelines.ai_cleaner import fetch_pubchem_properties
from backend.pipelines.logger import log_print

from dotenv import load_dotenv
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..")) 
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env"))

NCBI_KEY = os.getenv("NCBI_API_KEY")
if NCBI_KEY:
    metapub.config.NCBI_API_KEY = NCBI_KEY

def get_session():
    session = requests.Session()
    retries = Retry(
        total=5, 
        backoff_factor=2,  
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def pipeline_fetch_abstract_api(pmid: str) -> str:
    ncbi_key = os.getenv("NCBI_API_KEY", "").strip()
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=abstract&retmode=xml"
    if ncbi_key: 
        url += f"&api_key={ncbi_key}"
    try:
        time.sleep(random.uniform(0.5, 1.2))
        res = get_session().get(url, timeout=12)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            abstract_text = " ".join([elem.text for elem in root.iter('AbstractText') if elem.text])
            return abstract_text.strip()
    except: 
        pass
    return ""

def extract_key_sections_from_pmc(pmid: str) -> str:
    log_print(f"  正在为 PMID: {pmid} 检索 PMC 全文 HTML...")
    time.sleep(random.uniform(1.0, 2.0))
    fetch = PubMedFetcher()
    p_article = fetch.article_by_pmid(pmid)
    
    pmcid = getattr(p_article, 'pmc', None)
    if not pmcid and p_article.history:
        pmcid = p_article.history.get('pmc')
    
    if not pmcid:
        raise FileNotFoundError("NO_OA_FULLTEXT")

    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'
    }
    
    try:
        time.sleep(random.uniform(3.0, 5.5)) # 适度控速防封
        response = get_session().get(url, headers=headers, timeout=30)
        
        if response.status_code == 403:
            log_print("     遭到了 403 拦截，触发熔断。")
            raise ConnectionRefusedError("NCBI_403_FORBIDDEN")
        elif response.status_code == 429:
            log_print("     遭到了 429 频率限制。")
            raise ConnectionRefusedError("NCBI_429_LIMIT")
            
        response.raise_for_status()
        
        root = etree.HTML(response.content)
        containers = ['//div[@class="article-body"]', '//div[@id="mc-article"]', '//article']
        paragraphs = []
        for c in containers:
            found = root.xpath(f'{c}//p')
            if len(found) > 10:
                paragraphs = found
                break
        
        if not paragraphs:
            paragraphs = root.xpath('//body//p')

        clean_lines = []
        for p in paragraphs:
            text = p.xpath('string()').strip()
            if len(text) > 40 and "ref-type" not in str(p.attrib):
                clean_lines.append(text)
        
        text_content = "\n".join(clean_lines)

        if len(text_content) < 800:
            raise FileNotFoundError("TEXT_TOO_SHORT")
            
        log_print(f"     解析成功！有效文本长度: {len(text_content)}")
        return text_content[:15000]

    except Exception as e:
        log_print(f"     解析 PMC 失败: {e}")
        raise e

def export_manual_review_list(db_path=DB_PATH, output_csv="senolytics_manual_review_list.csv"):
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT pmid, title, status, reason FROM articles WHERE status >= 3 ORDER BY status ASC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        log_print(f"  [手动干预清单] 同步刷新: {output_csv}")
    except Exception as e:
        log_print(f"  导出复核清单失败: {e}")

def process_status_3_pool():
    init_db()
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("SELECT pmid, title, pmc_id FROM articles WHERE status = 3")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        log_print(" 数据库中暂无 [status=3] 的挂起文献。")
        return

    log_print("="*70)
    log_print(f" 启动【三阶全文深度挖掘流】，目标池容量: {len(rows)} 篇")
    log_print("="*70)

    fetcher = PubMedFetcher()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for pmid, title, pmc_id in rows:
        log_print(f"\n[🔬 全文层压榨 PMID:{pmid}] {title[:40]}...")
        time.sleep(random.uniform(1.0, 1.8))

        p_article = None
        abstract_from_fetcher = ""
        final_doi = "N/A"
        pub_date = "N/A"
        
        try:
            p_article = fetcher.article_by_pmid(pmid)
            final_doi = getattr(p_article, 'doi', "N/A")
            pub_date = p_article.pubdate.strftime("%Y-%m-%d") if hasattr(p_article, 'pubdate') and p_article.pubdate else "N/A"
            abstract_from_fetcher = getattr(p_article, 'abstract', "")
            
            if not pmc_id:
                pmc_id = getattr(p_article, 'pmc', None) or (p_article.history.get('pmc') if p_article.history else None)
                if pmc_id:
                    cursor.execute("UPDATE articles SET pmc_id=? WHERE pmid=?", (pmc_id, pmid))
                    conn.commit()
        except Exception as e:
            log_print(f"    元数据前置召回微瑕: {e}")

        full_context = None
        active_prompt = THIRD_STAGE_FULL_TEXT_PROMPT
        is_abstract_mode = False

        # 双轨分流决策系统
        if pmc_id:
            try:
                full_context = extract_key_sections_from_pmc(pmid)
            except (FileNotFoundError, requests.exceptions.HTTPError):
                log_print(f"    [网页全文缺失] 自动降级至【摘要互补模式】...")
                is_abstract_mode = True
            except (ConnectionRefusedError, requests.exceptions.RequestException) as net_err:
                log_print(f"    [网络熔断保护] 保持 status=3 挂起，避开防御墙。")
                continue
        else:
            log_print(f"    闭源文献，直接切入【摘要互补降级流】。")
            is_abstract_mode = True

        if is_abstract_mode:
            active_prompt = SECOND_STAGE_PROMPT
            full_context = abstract_from_fetcher if abstract_from_fetcher else pipeline_fetch_abstract_api(pmid)
            
            if not full_context or len(full_context.strip()) < 10:
                doi_url = f"https://doi.org/{final_doi}" if final_doi != "N/A" else "无 DOI"
                reason = f"非 OA 且无有效内容，流转至手动。DOI: {doi_url}"
                cursor.execute("UPDATE articles SET status=4, reason=? WHERE pmid=?", (reason, pmid))
                conn.commit()
                continue

        # 驱动弹性智脑
        log_print(f"    AI 执行特征抠取 (模式: {'摘要降级' if is_abstract_mode else '全文本'})")
        t3_res = call_doubao_json(full_context, active_prompt)
        
        if not t3_res or not isinstance(t3_res, dict):
            log_print("    AI 返回无效，留存池中下次重跑。")
            continue

        found = t3_res.get("is_specific_compound_found") if not is_abstract_mode else "YES"
        raw_compound_name = t3_res.get("compound_name")
        c_name = str(raw_compound_name).strip() if raw_compound_name else "UNKNOWN"

        if (not is_abstract_mode and found == "NO") or c_name.upper() in ["UNKNOWN", "NONE", "UNKNOWN_CLASS_ONLY"]:
            cursor.execute("UPDATE articles SET status=1, reason='全文深度研读，确认无Senolytic单体分子' WHERE pmid=?", (pmid,))
            conn.commit()
            log_print(f"    判定为假阳性噪声，安全清洗切断 [status=1]")
            continue

        # 切分洗涤池
        c_name_standardized = c_name.replace('(', ',').replace(')', ',').replace('[', ',').replace(']', ',')
        noise_pattern = re.compile(r'(?i)\b(senolytics|senolytic|combination|cocktail|treatment|group|dose|agent|compound|extract|inhibitor)\b')
        c_name_cleaned = noise_pattern.sub('', c_name_standardized).strip()
        split_items = [x.strip() for x in re.split(r'[,;，；、/]|\band\b', c_name_cleaned, flags=re.IGNORECASE)]
        
        compound_list = []
        for item in split_items:
            if item and len(item) >= 2 and item.upper() not in ["UNKNOWN", "NONE", "N/A"]:
                if item not in compound_list: compound_list.append(item)

        if not compound_list:
            cursor.execute("UPDATE articles SET status=4, reason='大模型提取物经系统清洗规则后被判为空白' WHERE pmid=?", (pmid,))
            conn.commit()
            continue

        # 并行多分子持久化入库
        actual_inserted_or_exists = 0  

        for single_compound in compound_list:
            if len(single_compound) > 45: continue
            
            log_print(f"   🧬 正在装载独立分子: [{single_compound}]")
            final_doi_param = final_doi if final_doi != "N/A" else (t3_res.get("doi") or "N/A")

            try:
                pubchem_props = fetch_pubchem_properties(single_compound) or {}
            except:
                pubchem_props = {}

            #  【关键修复：校准锚点传入顺序】先传 full_context，再传小药名单体
            invitro_raw = t3_res.get("in_vitro_data") or ""
            inv_raw = t3_res.get("in_vivo_data") or ""
            in_vitro_anchor = generate_safe_text_anchor(full_context, single_compound) if (invitro_raw and not is_abstract_mode) else invitro_raw
            in_vivo_anchor = generate_safe_text_anchor(full_context, single_compound) if (inv_raw and not is_abstract_mode) else inv_raw

            #  【方案二融合】抽取长尾字段做成打包柔性槽
            slot_data = {
                "chembl_id": pubchem_props.get("chembl_id", "N/A"),
                "drugbank_id": pubchem_props.get("drugbank_id", "N/A"),
                "drug_likeness": pubchem_props.get("drug_likeness", "N/A"),
                "inchikey": pubchem_props.get("inchikey", "N/A"),
                "extracted_indications": t3_res.get("indications") or "N/A"
            }

            try:
                #  【关键修复：19 个核心参数完全对齐，不再丢失或错位】
                cursor.execute('''
                    INSERT OR IGNORE INTO senolytic_compounds (
                        compound_name, common_names, description, cas_number, smiles, 
                        inchikey, drug_likeness, pmid, chembl_id, drugbank_id, 
                        doi, indications, hypotheses_summary, in_vitro_data, in_vitro_anchor, 
                        in_vivo_data, in_vivo_anchor, pub_date, pmc_id, additional_metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(single_compound), 
                    str(pubchem_props.get("common_name", "N/A")), 
                    str(t3_res.get("description") or ""),
                    str(pubchem_props.get("cas_number", "N/A")), 
                    str(pubchem_props.get("smiles", "N/A")),
                    str(pubchem_props.get("inchikey", "N/A")), 
                    str(pubchem_props.get("drug_likeness", "N/A")),
                    str(pmid), 
                    str(pubchem_props.get("chembl_id", "N/A")), 
                    str(pubchem_props.get("drugbank_id", "N/A")),
                    str(final_doi_param), 
                    str(t3_res.get("indications") or ""), 
                    str(t3_res.get("hypotheses_summary") or ""),
                    str(invitro_raw), 
                    str(in_vitro_anchor if in_vitro_anchor else "N/A"), 
                    str(inv_raw), 
                    str(in_vivo_anchor if in_vivo_anchor else "N/A"), 
                    str(pub_date), 
                    str(pmc_id if pmc_id else "NON-OA"),
                    json.dumps(slot_data, ensure_ascii=False) # 柔性防爆扩展槽
                ))
                actual_inserted_or_exists += 1
            except Exception as sql_err:
                log_print(f"       SQL 物理层写入报错: {sql_err}")

        # 闭环状态结算
        if actual_inserted_or_exists > 0:
            reason_msg = '三阶流：摘要自愈策略挖掘成功' if is_abstract_mode else '三阶流：全文Html暴力解构大获全胜'
            cursor.execute("UPDATE articles SET status=2, reason=? WHERE pmid=?", (reason_msg, pmid))
            conn.commit()
            log_print(f"    结算归档！文献完美晋级 [status=2]")
        else:
            cursor.execute("UPDATE articles SET status=4, reason='多分子写入异常或被系统规则护甲反弹' WHERE pmid=?", (pmid,))
            conn.commit()

        time.sleep(random.uniform(2.5, 4.5))

    conn.close()
    log_print("\n【三阶全文挖掘清洗任务结束】\n")
    export_manual_review_list()

if __name__ == "__main__":
    process_status_3_pool()