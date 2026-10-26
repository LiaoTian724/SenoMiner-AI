
import os
from backend.data_fetcher.pubmed_crawler import PubMedCrawler
from backend.pipelines.logger import log_print

def batch_fetch_pubmed(config):
   
    log_print("正在将 pipelines.pubmed_scraper.batch_fetch_pubmed 转发至全新的 data_fetcher 组件...")
    
    # 实例化全新的抓取器
    crawler = PubMedCrawler()
    
    # 转换调用
    articles = crawler.auto_search_by_keyword(
        keyword=getattr(config, 'keyword', ''),
        total_fetch_num=getattr(config, 'total_fetch_num', 20),
        start_date=getattr(config, 'start_date', None),
        end_date=getattr(config, 'end_date', None),
        other_filters=getattr(config, 'other_filters', None)
    )
    