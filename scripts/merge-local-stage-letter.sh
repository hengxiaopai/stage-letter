#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/hengxiaopai/stage-letter.git"
REMOTE_BRANCH="main"
ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$(dirname "$ROOT")/stage-letter-backup-$STAMP"

echo "[Stage Letter] local merge starting"
echo "Project: $ROOT"
echo "Backup : $BACKUP_DIR"

if [[ ! -d "$ROOT" ]]; then
  echo "ERROR: project directory does not exist: $ROOT" >&2
  exit 1
fi

if [[ "$(basename "$ROOT")" != "stage-letter" ]]; then
  echo "ERROR: run this script from the existing stage-letter project root." >&2
  exit 1
fi

# 1) Safety backup before any Git mutation. Heavy generated directories are excluded.
mkdir -p "$BACKUP_DIR"
tar \
  --exclude='./.git' \
  --exclude='./node_modules' \
  --exclude='./miniprogram_npm' \
  --exclude='./dist' \
  --exclude='./build' \
  --exclude='./.next' \
  -cf - . | (cd "$BACKUP_DIR" && tar -xf -)

echo "PASS backup created"

# 2) Ensure secrets/build outputs are ignored BEFORE the first local commit.
touch .gitignore
append_ignore() {
  local line="$1"
  grep -Fqx "$line" .gitignore 2>/dev/null || printf '%s\n' "$line" >> .gitignore
}
append_ignore ".env"
append_ignore ".env.*"
append_ignore "!.env.example"
append_ignore "node_modules/"
append_ignore "miniprogram_npm/"
append_ignore "dist/"
append_ignore "build/"
append_ignore ".next/"
append_ignore "experiments/gate0a/data/*"
append_ignore "!experiments/gate0a/data/.gitkeep"

# 3) Initialize Git only when needed.
if [[ ! -d .git ]]; then
  if git init -b main >/dev/null 2>&1; then
    :
  else
    git init >/dev/null
    git checkout -b main >/dev/null
  fi
  echo "PASS git repository initialized"
else
  echo "INFO existing .git detected; reusing it"
fi

# Ensure an identity exists for local merge commits without changing global config.
if ! git config user.name >/dev/null 2>&1; then
  git config user.name "Stage Letter Local Merge"
fi
if ! git config user.email >/dev/null 2>&1; then
  git config user.email "stage-letter-local@invalid"
fi

# 4) Capture the existing WeChat mini-program as the local baseline.
git add -A
if ! git diff --cached --quiet; then
  git commit -m "chore: import existing Stage Letter mini program" >/dev/null
  echo "PASS local mini-program baseline committed"
else
  echo "INFO no local baseline changes to commit"
fi

# 5) Attach/fetch the canonical Stage Letter remote.
if git remote get-url origin >/dev/null 2>&1; then
  CURRENT_ORIGIN="$(git remote get-url origin)"
  if [[ "$CURRENT_ORIGIN" != "$REPO_URL" && "$CURRENT_ORIGIN" != "git@github.com:hengxiaopai/stage-letter.git" ]]; then
    echo "ERROR: existing origin points elsewhere: $CURRENT_ORIGIN" >&2
    echo "Backup is safe at: $BACKUP_DIR" >&2
    exit 2
  fi
else
  git remote add origin "$REPO_URL"
fi

git fetch origin "$REMOTE_BRANCH"
echo "PASS remote Gate 0A history fetched"

# 6) Merge unrelated histories. Local app wins only on overlapping conflict hunks;
#    all non-overlapping remote Gate 0A files are added normally.
if git merge-base HEAD "origin/$REMOTE_BRANCH" >/dev/null 2>&1; then
  git merge "origin/$REMOTE_BRANCH" --no-edit
else
  git merge "origin/$REMOTE_BRANCH" \
    --allow-unrelated-histories \
    -X ours \
    -m "merge: combine local mini program with Stage Letter Gate 0A"
fi

echo "PASS histories merged"

# Re-assert secret ignores in case the remote/local .gitignore overlap was resolved locally.
touch .gitignore
append_ignore ".env"
append_ignore ".env.*"
append_ignore "!.env.example"
append_ignore "node_modules/"
append_ignore "miniprogram_npm/"
append_ignore "dist/"
append_ignore "build/"
append_ignore ".next/"
append_ignore "experiments/gate0a/data/*"
append_ignore "!experiments/gate0a/data/.gitkeep"

if ! git diff --quiet -- .gitignore; then
  git add .gitignore
  git commit -m "chore: preserve local secret and build ignores" >/dev/null
fi

# 7) Required Gate 0A assets must now exist alongside the existing mini-program.
required=(
  "experiments/gate0a/tikhub_probe.py"
  "experiments/gate0a/local_proxy.py"
  "experiments/gate0a/start-local.ps1"
  "reports/GATE-0A-DOUYIN.md"
)
for path in "${required[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "ERROR: merged repository is missing required file: $path" >&2
    echo "Restore backup if necessary: $BACKUP_DIR" >&2
    exit 3
  fi
done

echo "PASS Gate 0A assets verified"
echo
echo "=== MERGE COMPLETE ==="
echo "Backup: $BACKUP_DIR"
echo "Branch: $(git branch --show-current)"
echo "HEAD  : $(git rev-parse --short HEAD)"
echo
echo "Working tree:"
git status --short

echo
echo "Next local command:"
echo "powershell -ExecutionPolicy Bypass -File .\\experiments\\gate0a\\start-local.ps1"
echo
echo "NOTE: this script does NOT push your existing local mini-program to GitHub automatically."
