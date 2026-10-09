#!/usr/bin/env bash
# Підключає скіли з папки skills/ до Claude Code та OpenAI Codex (папка проєкту і папка користувача).
# Запуск із кореня репозиторію: ./install/install-skills.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/skills"
for t in "$root/.claude/skills" "$root/.agents/skills" "$HOME/.claude/skills" "$HOME/.agents/skills"; do
  mkdir -p "$t"
  for d in "$src"/*/; do
    name="$(basename "$d")"
    rm -rf "$t/$name"
    cp -R "$d" "$t/$name"
  done
  echo "Скіли скопійовано в $t"
done
echo "Готово. Перезапустіть агента, щоб він побачив нові скіли."
