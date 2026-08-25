"""项目改名: stage-letter/StageLetter/开场信 → stage-letter/StageLetter/开场信。

替换规则(注意顺序,先长后短避免互相污染):
  1. "StageLetter"      → "StageLetter"
  2. "stage-letter"      → "stage-letter"
  3. "stage_letter"      → "stage_letter"   (Python 包名/标识符)
  4. "stageletter"       → "stageletter"    (docker 容器名/DB 用户/密码)
  5. "STAGE_LETTER_"     → "STAGE_LETTER_"  (环境变量前缀)
  6. "开场信"        → "开场信"
  7. "Stage-Letter"      → "Stage-Letter"   (罕见写法)

排除:
  - .venv / __pycache__ / .git / node_modules
  - 二进制文件(.png/.jpg/.ico/.pyc/.db)
  - experiments/data/(jsonl/log 数据,含旧实验记录,保留原名无害)
  - .workbuddy-ai
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(r"G:\workbuddy\code\stage-letter")

# (旧, 新) — 按顺序应用
REPLACEMENTS = [
    ("STAGE_LETTER_", "STAGE_LETTER_"),
    ("StageLetter", "StageLetter"),
    ("Stage-Letter", "Stage-Letter"),
    ("stage-letter", "stage-letter"),
    ("stage_letter", "stage_letter"),
    ("stageletter", "stageletter"),
    ("开场信", "开场信"),
    ("开场信(StageLetter)", "开场信(StageLetter)"),
]

SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".workbuddy-ai", "pw_douyin_profile"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pyc", ".db", ".woff", ".woff2", ".ttf"}
# 数据文件不改(保留实验记录原名;内容里一般也没有项目名)
SKIP_EXT = {".jsonl", ".log", ".summary.json"}


def should_skip(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    if path.suffix.lower() in BINARY_EXT:
        return True
    if path.name.endswith(tuple(e for e in SKIP_EXT if e.endswith(".json"))):
        return True
    if path.suffix == ".jsonl" or path.name.endswith(".jsonl"):
        return True
    if path.suffix == ".log":
        return True
    return False


def main() -> int:
    changed_files = 0
    total_replacements = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            # 尝试 GBK / 或跳过
            try:
                text = path.read_text(encoding="gbk")
            except Exception:
                continue
        orig = text
        count = 0
        for old, new in REPLACEMENTS:
            if old in text:
                count += text.count(old)
                text = text.replace(old, new)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            changed_files += 1
            total_replacements += count
            if count:
                print(f"  {path.relative_to(ROOT)}: {count} 处")
    print(f"\n✓ 共修改 {changed_files} 个文件,替换 {total_replacements} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
