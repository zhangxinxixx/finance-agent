#!/usr/bin/env bash
set -euo pipefail

SESSION="finance-dev"
MAIN="/home/zxx/workspace/finance-agent"
WT_ROOT="/home/zxx/workspace/worktrees/finance-agent"
FE="$WT_ROOT/frontend"
BE="$WT_ROOT/backend"
REVIEW="$WT_ROOT/integration"
WORKBENCH="/home/zxx/workspace/finance-agent-workbench"
LOGS="$WORKBENCH/logs"

mkdir -p "$LOGS/tmux" "$LOGS/services" "$LOGS/agents"

normalize_existing_session() {
  local pane_ids=()

  tmux rename-window -t "$SESSION" "dev-board" 2>/dev/null || true
  mapfile -t pane_ids < <(tmux list-panes -t "$SESSION:dev-board" -F '#{pane_id}' 2>/dev/null || true)

  [ -n "${pane_ids[0]:-}" ] && tmux select-pane -t "${pane_ids[0]}" -T "0-hermes" || true
  [ -n "${pane_ids[1]:-}" ] && tmux select-pane -t "${pane_ids[1]}" -T "1-frontend-tui" || true
  [ -n "${pane_ids[2]:-}" ] && tmux select-pane -t "${pane_ids[2]}" -T "2-backend-tui" || true
}

session_matches_expected_layout() {
  local windows panes titles

  windows=$(tmux list-windows -t "$SESSION" 2>/dev/null | wc -l | tr -d ' ')
  panes=$(tmux list-panes -t "$SESSION:dev-board" 2>/dev/null | wc -l | tr -d ' ')

  if [ "$windows" != "1" ] || [ "$panes" != "3" ]; then
    return 1
  fi

  mapfile -t titles < <(tmux list-panes -t "$SESSION:dev-board" -F '#{pane_title}' 2>/dev/null || true)
  [ "${titles[0]:-}" = "0-hermes" ] || return 1
  [ "${titles[1]:-}" = "1-frontend-tui" ] || return 1
  [ "${titles[2]:-}" = "2-backend-tui" ] || return 1

  return 0
}

if tmux has-session -t "$SESSION" 2>/dev/null; then
  normalize_existing_session
  if ! session_matches_expected_layout; then
    if [ "${DEV_FINANCE_REBUILD:-}" = "1" ]; then
      tmux kill-session -t "$SESSION"
    else
      echo "ERROR: existing tmux session $SESSION has unexpected layout." >&2
      echo "Current windows:" >&2
      tmux list-windows -t "$SESSION" -F '#I:#W panes=#{window_panes}' >&2
      echo "Run with DEV_FINANCE_REBUILD=1 ./scripts/dev-tmux.sh to rebuild the session." >&2
      exit 1
    fi
  else
  if [ "${DEV_FINANCE_NO_ATTACH:-}" = "1" ]; then
    echo "tmux session already exists: $SESSION"
    tmux list-windows -t "$SESSION" -F '#I:#W'
    tmux list-panes -t "$SESSION" -F '#P title=#{pane_title} path=#{pane_current_path}'
    exit 0
  fi
  tmux attach -t "$SESSION"
  exit 0
  fi
fi

if [ ! -d "$MAIN/.git" ]; then
  echo "ERROR: $MAIN 不是 git 仓库。"
  exit 1
fi

FE_CWD="$FE"
BE_CWD="$BE"
[ -d "$FE_CWD" ] || FE_CWD="$MAIN"
[ -d "$BE_CWD" ] || BE_CWD="$MAIN"

tmux new-session -d -s "$SESSION" -n "0-hermes" -c "$MAIN"
tmux rename-window -t "$SESSION" "dev-board"
HERMES_PANE="$(tmux list-panes -t "$SESSION:dev-board" -F '#{pane_id}' | head -n 1)"
tmux select-pane -t "$HERMES_PANE" -T "0-hermes"
tmux send-keys -t "$HERMES_PANE" "cd $MAIN && clear && echo '0-hermes | Hermes 主控：目标 / 边界 / 风险 / 验收' && echo && git status --short && echo && echo '当前任务：docs/dev/current-task.md' && echo '派发前端：scripts/dev-dispatch.sh frontend <task-file>' && echo '派发后端：scripts/dev-dispatch.sh backend <task-file>' && echo '强制 job：DEV_DISPATCH_FORCE_JOB=1 scripts/dev-dispatch.sh frontend <task-file>' && echo '任务文件建议放 hermes/prompts/ 或 docs/dev/tasks/'" C-m

FRONTEND_PANE="$(tmux split-window -h -t "$HERMES_PANE" -c "$FE_CWD" -P -F '#{pane_id}')"
tmux select-pane -t "$FRONTEND_PANE" -T "1-frontend-tui"
tmux send-keys -t "$FRONTEND_PANE" "cd $FE_CWD && clear && echo '1-frontend-tui | 前端 Codex 交互窗口' && echo '启动：codex --no-alt-screen --profile frontend' && echo '范围：apps/frontend-web；不改后端/数据库/AGENTS.md' && echo && git status --short" C-m

BACKEND_PANE="$(tmux split-window -v -t "$FRONTEND_PANE" -c "$BE_CWD" -P -F '#{pane_id}')"
tmux select-pane -t "$BACKEND_PANE" -T "2-backend-tui"
tmux send-keys -t "$BACKEND_PANE" "cd $BE_CWD && clear && echo '2-backend-tui | 后端 Codex 交互窗口' && echo '启动：codex --no-alt-screen --profile backend' && echo '范围：api/worker/collectors/parsers/features/analysis/renderer/tests；不改前端布局/AGENTS.md' && echo && git status --short" C-m

tmux select-layout -t "$SESSION:dev-board" main-vertical >/dev/null || true
tmux resize-pane -t "$HERMES_PANE" -x 70 >/dev/null 2>&1 || true
tmux select-pane -t "$HERMES_PANE"

if [ "${DEV_FINANCE_NO_ATTACH:-}" = "1" ]; then
  echo "tmux session created: $SESSION"
  tmux list-windows -t "$SESSION" -F '#I:#W'
  tmux list-panes -t "$SESSION:dev-board" -F '#P title=#{pane_title} path=#{pane_current_path}'
  exit 0
fi

tmux attach -t "$SESSION"
