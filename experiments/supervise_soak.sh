#!/usr/bin/env bash
# supervise_soak.sh — soak 监督器:进程被杀后自动重启,直到累计时长达标
#
# 背景:本环境后台进程运行 3-12h 后会被外部终止(8/2、8/4 两次 soak 均被杀,
# 未写出 summary.json)。本脚本以"短批次 + 自动重启"方式累积浸泡时长,
# 每个批次 2h,退出(无论正常完成还是被杀)后 30s 自动重启下一批,
# 直到累计运行 ≥ total_hours。数据全部追加在 jsonl,跨批次不丢失。
#
# 用法:
#   bash experiments/supervise_soak.sh bilibili 24 600
#     platform=必选(bilibili|douyin|huya|douyu)
#     total_hours=累计目标(默认 24)
#     interval=轮询间隔秒(默认按平台)
#     soak_type=correctness(默认)
#
# 输出:
#   experiments/data/supervise_{platform}_v{pid}.log — 监督器自身日志
#   每个批次: experiments/data/{platform}_24h-{ts}.log/.jsonl
#
# 注意:用 nohup + 独立进程跑,避免被当前 shell 的退出拖死:
#   nohup bash experiments/supervise_soak.sh bilibili 24 600 >/dev/null 2>&1 &

set -u
PLATFORM="${1:?platform required: bilibili|douyin|huya|douyu}"
TOTAL_HOURS="${2:-24}"
INTERVAL="${3:-}"
SOAK_TYPE="${4:-correctness}"
BATCH_HOURS=2

# 平台默认间隔
if [ -z "$INTERVAL" ]; then
  case "$PLATFORM" in
    bilibili) INTERVAL=300 ;;
    *) INTERVAL=600 ;;
  esac
fi

SCRIPT="experiments/${PLATFORM}_24h.py"
[ -f "$SCRIPT" ] || { echo "找不到 $SCRIPT"; exit 2; }

DATA_DIR="experiments/data"
mkdir -p "$DATA_DIR"
SUP_LOG="$DATA_DIR/supervise_${PLATFORM}_$$.log"

START_TS=$(date +%s)
END_AT=$((START_TS + TOTAL_HOURS * 3600))
BATCH_SECS=$((BATCH_HOURS * 3600))
BATCH_N=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SUP_LOG"; }

log "supervisor 启动: platform=$PLATFORM total=${TOTAL_HOURS}h batch=${BATCH_HOURS}h interval=${INTERVAL}s type=$SOAK_TYPE"
log "日志: $SUP_LOG"

while [ "$(date +%s)" -lt "$END_AT" ]; do
  BATCH_N=$((BATCH_N + 1))
  # 剩余时长 = min(BATCH_SECS, END_AT - now)
  REMAIN=$((END_AT - $(date +%s)))
  DUR=$(( BATCH_SECS < REMAIN ? BATCH_SECS : REMAIN ))
  DUR_H=$(awk "BEGIN{printf \"%.1f\", $DUR/3600}")
  log "批次 $BATCH_N 启动: duration=${DUR_H}h (剩余 $((REMAIN/60))min)"
  PYTHONPATH=. ./.venv/Scripts/python.exe "$SCRIPT" \
      --soak-type "$SOAK_TYPE" \
      --duration-hours "$DUR_H" \
      --interval-seconds "$INTERVAL" \
      >> "$SUP_LOG" 2>&1
  RC=$?
  log "批次 $BATCH_N 退出 rc=$RC, 30s 后重启下一批"
  sleep 30
done

log "supervisor 结束: 累计时长达标(${TOTAL_HOURS}h)"
