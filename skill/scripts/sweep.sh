#!/bin/bash
# Периодический обход дежурного. Запускается launchd, см. com.egamza.factset-duty.plist
set -u

SKILL_DIR="$HOME/.claude/skills/factset-duty"
LOG="$SKILL_DIR/cases/sweep.log"
HOUR=$(date +%-H)

# Вне рабочего времени не будим: дежурный всё равно не отреагирует
if [ "$HOUR" -lt 10 ] || [ "$HOUR" -ge 20 ]; then
  exit 0
fi

# Запуск из Projects: там сконфигурирован Jira-MCP, из папки скилла его не видно
cd "$HOME/Projects" || exit 1

OUT=$(mktemp)

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %z') ==="
  claude -p "$(cat "$SKILL_DIR/scripts/sweep-prompt.txt")" \
    --add-dir "$SKILL_DIR" \
    --allowedTools "mcp__claude_ai_Slack__slack_search_public_and_private" \
                   "mcp__claude_ai_Slack__slack_read_channel" \
                   "mcp__claude_ai_Slack__slack_read_thread" \
                   "mcp__claude_ai_Slack__slack_get_reactions" \
                   "mcp__claude_ai_Slack__slack_send_message" \
                   "mcp__jira__jira_search" \
                   "mcp__jira__jira_get_issue" \
                   "Read" "Write" "Edit" "Bash" \
    2>&1 | tee "$OUT"
  echo
} >> "$LOG"

# Пинга в Slack от своего имени не выйдет: Slack не подсвечивает свои же
# сообщения. Поэтому дёргаем уведомлением macOS — видно сразу и стоит ноль.
if grep -q "🔵" "$OUT"; then
  CNT=$(grep -c "🔵" "$OUT")
  osascript -e "display notification \"Новых обращений: $CNT\" with title \"Дежурство FactSet\" sound name \"Ping\"" 2>/dev/null
fi
rm -f "$OUT"
