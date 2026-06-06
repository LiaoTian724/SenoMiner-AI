
import os
import time
import random
import re
import requests
from typing import List, Dict, Optional
from dotenv import load_dotenv
from metapub import PubMedFetcher

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..")) 
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
load_dotenv(dotenv_path=ENV_PATH)

NCBI_KEY = os.getenv("NCBI_API_KEY", "").strip()
if NCBI_KEY:
    os.environ["NCBI_API_KEY"] = NCBI_KEY
    os.environ["METAPUB_NCBI_API_KEY"] = NCBI_KEY
    print(f"成功捕获您的 NCBI 秘钥: {NCBI_KEY[:4]}***")

from backend.pipelines.logger import log_print
from ai_miner.db_manager import save_raw_article, DB_PATH
from backend.pipelines.ai_cleaner import batch_ai_process 

class PubMedCrawler:
    def __init__(self):
        """ 初始化统一的 PubMed 检索抓取器 """
        self.fetcher = PubMedFetcher()
        self.per_page_num = 100
        self.sleep_min = 0.2
        self.sleep_max = 0.85

    def _safe_fetch_article(self, pmid: str, retry: int = 3):
        for i in range(retry):
            try:
                return self.fetcher.article_by_pmid(pmid)
            except Exception as e:
                log_print(f"重试 {i+1}/{retry} PMID: {pmid} 获取失败, 原因: {str(e)[:50]}")
                time.sleep(random.uniform(1.5, 3.0))
        return None

    def _process_and_save(self, article, pmid: str) -> Optional[Dict]:
        """ 统一把 metapub 对象清洗、截断并落库 """
        if not article:
            return None
            
        abstract_text = article.abstract or "No abstract available."
        if len(abstract_text) > 15000:
            abstract_text = abstract_text[:15000] + "...[内容过长已截断]"
            
        pmc_id = getattr(article, 'pmc', None) or (article.history.get('pmc') if article.history else None)
        oa_status = 1 if pmc_id else 0  
        
        is_new = save_raw_article(
            pmid=pmid, 
            title=article.title, 
            abstract=abstract_text, 
            pmc_id=pmc_id,
            is_open_access=oa_status
        )
        
        status_msg = "落库成功!" if is_new else "本地已存在，信息覆盖更新"
        log_print(f"PMID: {pmid} 文献元数据抓取成功 ({status_msg} | OA状态: {oa_status})")
        
        pub_date = "Unknown"
        if article.pubdate:
            pub_date = article.pubdate.strftime("%Y-%m-%d") if hasattr(article.pubdate, 'strftime') else str(article.pubdate)

        return {
            "pmid": pmid,
            "doi": article.doi or "N/A",
            "title": article.title,
            "abstract": abstract_text,
            "pub_date": pub_date,
            "pmc_id": pmc_id,
            "is_open_access": oa_status,
            "journal": article.journal or "Unknown",
            "authors": ", ".join(article.authors) if article.authors else "Unknown"
        }

    # =========================================================================
    # 模式一：手动查模式 (DOI / PMID)   # PMID现在还没做
    # =========================================================================
    def fetch_single_by_pmid(self, pmid: str) -> Optional[Dict]:
        """ 直接通过 PMID 抓取，并同步 AI 清洗 """
        pmid = str(pmid).strip()
        log_print(f"\n正在检索目标 PMID: {pmid} ...")
        article = self._safe_fetch_article(pmid)
        result = self._process_and_save(article, pmid)

        if result:
            log_print(f"文献已成功读取。AI对 PMID {pmid} 化合物分析中...")
            batch_ai_process(db_path=DB_PATH, target_specific_pmid=pmid)
        
        return result

    #=================================================DOI没做, 有问题===============================================
    def fetch_single_by_doi(self, doi: str) -> Optional[Dict]:
        """ 通过 DOI 反查 PubMed 并抓取落库 """
        doi = str(doi).strip()
        log_print(f"\n正在通过 DOI 反查 PMID: {doi} ...")
        try:
            pmid = self.fetcher.pmid_for_doi(doi)
            if not pmid:
                url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={doi}[Location ID]&retmode=json"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    id_list = res.json().get("esearchresult", {}).get("idlist", [])
                    if id_list:
                        pmid = id_list[0]

            if pmid:
                log_print(f"DOI 成功找到 PMID: {pmid}")
                return self.fetch_single_by_pmid(pmid)
            else:
                log_print(f"无法在 NCBI 体系中将 DOI [{doi}] 查询为有效的 PMID。")
                return None
        except Exception as e:
            log_print(f"DOI 反查发生异常: {e}")
            return None

    # =========================================================================
    # 模式二：关键词批量自动查询 输入关键词及条件
    # =========================================================================
    def auto_search_by_keyword(self, 
                               keyword: str, 
                               total_fetch_num: int = 20, 
                               start_date: Optional[str] = None, 
                               end_date: Optional[str] = None,
                               other_filters: Optional[str] = None) -> List[Dict]:
        query_word = str(keyword).strip()
        full_query = query_word
        if start_date and end_date:
            full_query += f" AND ({start_date}[Date - Publication] : {end_date}[Date - Publication])"
        if other_filters:
            full_query += f" {other_filters}"

        log_print("=" * 70)
        log_print("PubMed 自动化文献检索...")
        log_print(f"{full_query}")
        log_print("=" * 70)

        all_pmids = []
        start_offset = 0

        while len(all_pmids) < total_fetch_num:
            try:
                page_pmids = self.fetcher.pmids_for_query(full_query, retmax=self.per_page_num, retstart=start_offset)
                if not page_pmids: break
                all_pmids.extend(page_pmids)
                start_offset += self.per_page_num
                time.sleep(random.uniform(1.0, 1.8))
            except Exception as e:
                log_print(f"分页检索 PMID 发生网络异常: {e}")
                break

        target_pmids = all_pmids[:total_fetch_num]
        articles_pool = []
        
        for idx, pmid in enumerate(target_pmids, 1):
            log_print(f"   [{idx}/{len(target_pmids)}] 正在处理 PMID: {pmid}")
            article = self._safe_fetch_article(pmid)
            if not article: continue
                
            cleaned_data = self._process_and_save(article, pmid)
            if cleaned_data:
                articles_pool.append(cleaned_data)
            time.sleep(random.uniform(self.sleep_min, self.sleep_max))

        return articles_pool