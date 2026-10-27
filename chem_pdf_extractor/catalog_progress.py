"""One local literature task with observable stages and resumable failure."""
from __future__ import annotations

import threading
import time
from .security import redact_sensitive_text

STAGES = {'loading': '读取论文', 'extracting': '分段提取', 'reviewing': '核对原文',
          'linking': '关联实验', 'enriching': '查询数据库', 'saving': '保存结果',
          'complete': '提取完成', 'failed': '提取失败', 'needs_pdf': '需要 PDF'}


class CatalogProgress:
    def __init__(self):
        self.lock = threading.Lock()
        self.task = None

    def start(self, source: str, kind: str) -> bool:
        with self.lock:
            if self.task and self.task['status'] == 'running':
                return False
            now = time.time()
            self.task = {'source': source, 'kind': kind, 'status': 'running', 'stage': 'loading',
                         'message': '已开始，正在读取论文', 'error': '', 'completed': 0, 'total': 0,
                         'started_at': now, 'updated_at': now, 'finished_at': None, 'events': []}
            return True

    def update(self, stage: str, message: str = '', completed=None, total=None):
        with self.lock:
            if not self.task or self.task['status'] != 'running':
                return
            t = self.task
            if stage != t['stage']:
                t.update(stage=stage, completed=0, total=0)
            if completed is not None:
                t['completed'] = max(0, int(completed))
            if total is not None:
                t['total'] = max(0, int(total))
            if message:
                t['message'] = redact_sensitive_text(str(message))[:600]
            t['updated_at'] = time.time()

    def log(self, message: str):
        with self.lock:
            if not self.task or self.task['status'] != 'running':
                return
            now = time.time()
            text = redact_sensitive_text(str(message))[:600]
            self.task['events'] = (self.task['events'] + [{'time': now, 'message': text}])[-30:]
            self.task['updated_at'] = now

    def finish(self, error: str = '', *, needs_pdf: bool = False):
        with self.lock:
            if not self.task:
                return
            now = time.time()
            status = 'needs_pdf' if needs_pdf else ('failed' if error else 'complete')
            self.task.update(status=status, stage=status, error=redact_sensitive_text(str(error))[:800],
                             finished_at=now, updated_at=now)
            self.task['message'] = self.task['error'] or '提取完成，化合物列表已更新'

    def snapshot(self) -> dict:
        with self.lock:
            t = self.task
            if not t:
                return {'running': False, 'message': '', 'error': '', 'task': None}
            return {'running': t['status'] == 'running', 'message': t['message'], 'error': t['error'],
                    'task': {**t, 'events': list(t['events']), 'stage_label': STAGES.get(t['stage'], t['stage']),
                             'elapsed_seconds': max(0, int((t['finished_at'] or time.time()) - t['started_at']))}}
