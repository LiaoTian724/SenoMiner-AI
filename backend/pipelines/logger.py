
from typing import List
import threading

# 全局共享的日志缓冲池
task_logs: List[str] = []
log_lock = threading.Lock()  # 线程安全锁




def log_print(message: str):
    with log_lock:
        print(message)
        task_logs.append(message)
        if len(task_logs) > 1000:
            task_logs.pop(0)

def safe_clear_logs():
    with log_lock:
        task_logs.clear()

def get_logs():
    with log_lock:
        return list(task_logs)