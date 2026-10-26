
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import sqlite3

from backend.data_fetcher.pubmed_crawler import PubMedCrawler
from backend.pipelines.logger import log_print


from ai_miner.db_manager import (
    bump_all_compounds_by_pmid, 
    save_raw_article,
    insert_custom_compound,
    DB_PATH  # 引入数据库路径
)

router = APIRouter(prefix="/api/v1/scraper", tags=["文献数据采集网关"])

class AutoSearchRequest(BaseModel):
    keyword: str
    total_fetch_num: Optional[int] = 20
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    other_filters: Optional[str] = None

class ManualFetchRequest(BaseModel):
    pmid: Optional[str] = None
    doi: Optional[str] = None


@router.get("/manual_fetch")
@router.post("/manual_fetch")
async def api_manual_fetch(
    payload: Optional[ManualFetchRequest] = None,
    pmid: Optional[str] = Query(None),
    doi: Optional[str] = Query(None)
):
   
    target_pmid = pmid
    target_doi = doi
    
    if payload:
        if payload.pmid: target_pmid = payload.pmid
        if payload.doi: target_doi = payload.doi

    if not target_pmid and not target_doi:
        log_print("手动查询失败：未收到任何 pmid 或 doi")
        raise HTTPException(status_code=400, detail="手动查询失败：必须提供 pmid 或 doi 参数")

    crawler = PubMedCrawler()
    result = None
    
    log_print(f"1. 爬虫调度开始。输入参数 -> pmid: {target_pmid}, doi: {target_doi}")
    
    try:
        if target_pmid:
            log_print(f"正在检索目标 PMID: {str(target_pmid).strip()}")
            result = crawler.fetch_single_by_pmid(str(target_pmid).strip())
        elif target_doi:
            log_print(f"正在检索目标 DOI: {str(target_doi).strip()}")
            result = crawler.fetch_single_by_doi(str(target_doi).strip())
    except Exception as e:
        log_print(f"爬虫失败, 发生故障: {str(e)}")
        raise HTTPException(status_code=500, detail=f"发生错误: {str(e)}")
        
    if not result:
        log_print("检索结束, PubMed 未能匹配到此文献或底层网络超时")
        raise HTTPException(status_code=404, detail="精准检索结束，未能在 PubMed 中找到此文献。")

    # 解剖爬虫吐出的真实数据结构
    log_print(f"2. 爬虫返回结果成功。数据类型: {type(result)}")
    log_print(f"{str(result)[:1000]}") # 打印前1000个字符防止撑爆控制台

    resolved_pmid = None
    compounds_to_save = []

    if isinstance(result, dict):
        resolved_pmid = result.get("pmid")
        # 探测是否直接包含洗出来的化合物单体
        if "compound_name" in result:
            compounds_to_save.append(result)
        # 探测是否通过列表或嵌套结构藏在内部
        elif "compounds" in result and isinstance(result["compounds"], list):
            compounds_to_save = result["compounds"]
    elif isinstance(result, list):
        if len(result) > 0 and isinstance(result[0], dict):
            resolved_pmid = result[0].get("pmid")
            compounds_to_save = result
    else:
        resolved_pmid = getattr(result, "pmid", None)

    if not resolved_pmid:
        resolved_pmid = target_pmid

    if not resolved_pmid:
        log_print("彻底无法从返回结构中解出任何有效的 PMID 标识符")
        raise HTTPException(status_code=500, detail="爬虫解析异常：未能提取到有效的 PMID 标识符")

    resolved_pmid = str(resolved_pmid).strip()
    log_print(f"3. 身份标识锚定完成 -> 最终决定使用的 PMID 为: {resolved_pmid}")

    # 强制挂到主表
    title = "Manual Fetched Article"
    abstract = ""
    if isinstance(result, dict):
        title = result.get("title", "Manual Fetched Article")
        abstract = result.get("abstract", "")
        
    log_print(f"尝试存入文章主表。标题摘要长度: {len(abstract)}")
    save_raw_article(pmid=resolved_pmid, title=title, abstract=abstract, pmc_id=None, is_open_access=1)

    # 2. 如果解析到了化合物资产，在网关层执行一次硬核托管代入库
    log_print(f"4. 侦测到待托管入库的化合物数量: {len(compounds_to_save)}")
    if compounds_to_save:
        for idx, comp in enumerate(compounds_to_save):
            try:
                comp["pmid"] = resolved_pmid
                log_print(f"   正在入库 第 {idx+1} 个化合物: {comp.get('compound_name')}")
                insert_custom_compound(comp)
            except Exception as item_err:
                log_print(f"   警告: 第 {idx+1} 个小分子入库失败: {item_err}")

    # 3. 执行捆绑置顶时间轴托举
    bump_all_compounds_by_pmid(resolved_pmid)

    log_print("5. 开始闭环前最后现场数据库核验...")
    db_count = 0
    conn = None
    cursor = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0) 
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM senolytic_compounds WHERE pmid = ?", (resolved_pmid,))
        db_count = cursor.fetchone()[0]
        log_print(f"数据库目前真实存在的该文献小分子数量为: {db_count} 个")
    except sqlite3.Error as sqlite_err:
        log_print(f"数据库发生死锁、损坏或权限异常: {sqlite_err}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    # 5. 反馈状态
    if db_count == 0:
        return {
            "status": "success",
            "message": f"文献定位并触发托举，但目前数据库化合物子表中该 PMID ({resolved_pmid}) 对应的记录数为 0。AI 可能未洗出化合物或仍在异步清洗中。",
            "data": result,
            "count": 0
        }
    
    return {
        "status": "success", 
        "message": f"手动精准托举成功！已为您打包置顶该文献下的 {db_count} 个小分子资产。", 
        "data": result,
        "count": db_count
    }


@router.post("/auto_search")
async def api_auto_search(payload: AutoSearchRequest):
    try:
        crawler = PubMedCrawler()
        results = crawler.auto_search_by_keyword(
            keyword=payload.keyword,
            total_fetch_num=payload.total_fetch_num,
            start_date=payload.start_date,
            end_date=payload.end_date,
            other_filters=payload.other_filters
        )
        
        if results and isinstance(results, list):
            for article in results:
                p_id = article.get("pmid") if isinstance(article, dict) else getattr(article, "pmid", None)
                if p_id:
                    bump_all_compounds_by_pmid(str(p_id))

        return {"status": "success", "fetched_count": len(results), "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自动群查流程突发溃败: {str(e)}")