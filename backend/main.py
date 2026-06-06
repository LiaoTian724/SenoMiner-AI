
# backend/main.py
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))   
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))  

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from ai_miner.db_manager import init_db, DB_PATH
from backend.pipelines.pubmed_scraper import batch_fetch_pubmed
from backend.pipelines.logger import task_logs, log_print, safe_clear_logs

from backend.routers.scraper import router as scraper_router
from backend.routers.compounds import router as compounds_router




app = FastAPI(title="Senolytics Repository API Platform", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 挂载核心控制网关
app.include_router(scraper_router)
app.include_router(compounds_router)

@app.get("/")
def root():
    return {"status": "running", "message": "Senolytics Backend Center is Running."}

# --- AI 自动化管理区 ---
scraper_running = False
scraper_status_message = "系统空闲"

class ScraperConfig(BaseModel):
    keyword: str = "senolytics"
    start_date: str = "2010/01/01"
    end_date: str = "2025/12/31"
    total_fetch_num: int = 10
    other_filters: Optional[str] = ""

@app.on_event("startup")
def startup_event():
    init_db()  # 确保带扩展槽的全新表结构存在
    log_print(f"数据库环境拓扑初始化就绪！当前主库绝对路径: {os.path.abspath(DB_PATH)}")

def CorePipelineTask(config: ScraperConfig):
    global scraper_running, scraper_status_message
    scraper_running = True
    try:
        log_print("======================================================================")
        log_print("[中控台启动] 自动化文献捕获流水线已启动...")
        log_print("======================================================================")
        
        scraper_status_message = "正在批量抓取 PubMed 文献中..."
        batch_fetch_pubmed(config)
        
        scraper_status_message = "正在调起大模型进行摘要初筛..."
        try:
            from backend.pipelines.ai_cleaner import batch_ai_process
            batch_ai_process(os.path.abspath(DB_PATH))
        except Exception as e:
            log_print(f"摘要 AI 初筛阶段遇到波动: {e}")

        scraper_status_message = "任务完成！"
    except Exception as e:
        scraper_status_message = "运行发生异常中断"
        log_print(f"\n流水线遭遇阻碍: {str(e)}")
    finally:
        scraper_running = False


# 自动化中心控制接口
@app.post("/api/v1/scraper/run")
def run_pipeline(config: ScraperConfig, background_tasks: BackgroundTasks):
    global scraper_running
    if scraper_running:
        return {"status": "warning", "message": "后台任务正在高负荷运转中，请勿重复调起！"}
    
    background_tasks.add_task(CorePipelineTask, config)
    return {"status": "success", "message": "后台流水线已挂起！开始自动抓取落库。"}

@app.get("/api/v1/scraper/status")
def get_scraper_status():
    return {
        "is_running": scraper_running,
        "message": scraper_status_message,
        "logs": task_logs
    }