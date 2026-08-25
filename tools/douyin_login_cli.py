"""抖音扫码登录 CLI(P0-S1)。

用法:
  python tools/douyin_login_cli.py login    # 扫码登录(headed 浏览器, 需桌面)
  python tools/douyin_login_cli.py status   # 查看登录态
  python tools/douyin_login_cli.py probe    # 重新探测登录态
  python tools/douyin_login_cli.py logout   # 登出(清 profile)
  python tools/douyin_login_cli.py clean    # 清空全部
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services.douyin_session import main

if __name__ == "__main__":
    main()
