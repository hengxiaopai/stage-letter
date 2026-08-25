"""一键启动所有常驻进程(P0: 心跳机制不依赖人工/会话)。

用法:
  python tools/start_all.py           # 启动全部(检查 docker → uvicorn → probe worker)
  python tools/start_all.py --worker  # 只启动 probe worker
  python tools/start_all.py --api     # 只启动 API

进程使用 DETACHED_PROCESS 脱离会话, 不依赖 bash/agent 存活。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / ".workbuddy"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def run_detached(args: list[str], log_name: str) -> None:
    with open(LOG_DIR / log_name, "a", encoding="utf-8") as f:
        subprocess.Popen(
            args,
            cwd=str(ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=DETACHED,
            close_fds=True,
        )
    print(f"  ✓ {log_name} 已启动: {' '.join(args[-3:])}")


def ensure_docker() -> None:
    """检查并启动 postgres/redis 容器。"""
    import socket

    def _db_up() -> bool:
        try:
            s = socket.create_connection(("127.0.0.1", 5432), timeout=2)
            s.close()
            return True
        except OSError:
            return False

    if _db_up():
        print("  ✓ PostgreSQL 已就绪")
        return

    print("  … PostgreSQL 未就绪, 尝试启动 Docker 容器")
    for c in ("stageletter-postgres", "stageletter-redis"):
        subprocess.run(["docker", "start", c], capture_output=True)
    # 等待 DB 就绪(最多 60s)
    for i in range(30):
        if _db_up():
            print("  ✓ PostgreSQL 已启动")
            return
        time.sleep(2)
    print("  ⚠ PostgreSQL 60s 内未就绪, 请手动检查 Docker Desktop")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true", help="只启动 probe worker")
    ap.add_argument("--api", action="store_true", help="只启动 API")
    args = ap.parse_args()

    if args.api:
        run_detached([str(PY), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8899"], "uvicorn.log")
    elif args.worker:
        run_detached([str(PY), "-m", "workers.probe.worker", "--loop", "--interval", "30"], "probe_worker.log")
    else:
        ensure_docker()
        # 避免重复启动: 简单探测端口
        import socket

        def _port_open(port: int) -> bool:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
                s.close()
                return True
            except OSError:
                return False

        if not _port_open(8899):
            run_detached([str(PY), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8899"], "uvicorn.log")
        else:
            print("  ✓ API(8899) 已在运行")
        run_detached([str(PY), "-m", "workers.probe.worker", "--loop", "--interval", "30"], "probe_worker.log")
    print("\n完成。检查日志: .workbuddy/uvicorn.log, .workbuddy/probe_worker.log")


if __name__ == "__main__":
    main()
