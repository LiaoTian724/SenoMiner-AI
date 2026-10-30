"""One web service per checkout, so different code versions cannot share output."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import urllib.request


def code_generation(root: Path) -> str:
    digest = hashlib.sha256()
    package = Path(root) / 'chem_pdf_extractor'
    files = sorted(package.glob('*.py')) + sorted((package / 'templates').glob('*.html'))
    files += sorted((package / 'static').glob('catalog.*'))
    for path in files:
        digest.update(str(path.relative_to(package)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class WebInstance:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.generation = code_generation(self.root)
        self.instance_id = secrets.token_hex(16)
        self.file = None
        self.owned = False

    def acquire(self) -> bool:
        target = self.root / 'output' / '.web-instance.lock'
        target.parent.mkdir(parents=True, exist_ok=True)
        self.file = target.open('a+b')
        # Windows requires a real byte at the locked offset.
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b' ')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return False
        self.owned = True
        # A crashed owner's stale registry cannot survive successful acquisition.
        self.file.seek(0)
        self.file.truncate()
        self.file.write(b' ')
        self.file.flush()
        return True

    def publish(self, port: int) -> None:
        if not self.owned:
            raise RuntimeError('Web service lock is not held')
        data = {'port': port, 'pid': os.getpid(), 'instance_id': self.instance_id,
                'generation': self.generation}
        self.file.seek(0)
        self.file.truncate()
        self.file.write(b' ' + json.dumps(data).encode())
        self.file.flush()

    def existing_url(self) -> str:
        for _ in range(40):
            self.file.seek(0)
            try:
                data = json.loads(self.file.read()[1:])
            except (ValueError, UnicodeDecodeError):
                time.sleep(.1)
                continue
            port = data.get('port')
            if type(port) is not int or not 1 <= port <= 65535:
                break
            url = f'http://127.0.0.1:{port}'
            try:
                with urllib.request.urlopen(url + '/local-instance', timeout=1) as response:
                    live = json.load(response)
                if live.get('instance_id') != data.get('instance_id'):
                    break
            except (OSError, ValueError):
                time.sleep(.1)
                continue
            if data.get('generation') != self.generation:
                raise RuntimeError('项目代码已更新，旧服务仍在运行。请关闭原启动窗口后重新启动；不会另开端口继续写入同一结果。')
            return url + '/catalog'
        raise RuntimeError('项目服务正在启动或退出，请稍后重试；不会重复启动。')

    def close(self) -> None:
        if self.file is not None:
            if self.owned:
                self.file.seek(0)
                self.file.truncate()
                self.file.write(b' ')
                self.file.flush()
                if os.name == 'nt':
                    import msvcrt
                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None
            self.owned = False
