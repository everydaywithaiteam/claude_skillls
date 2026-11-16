#!/bin/bash
# Auto-commit and push any changes in the skills repo.
# Run by a Claude Code SessionEnd hook (see ~/.claude/settings.json).
# Safe to run by hand too: does nothing when there are no changes.

REPO="/Users/sam/Claude/skills"
LOG="$REPO/.hooks/autocommit.log"

cd "$REPO" || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Nothing changed -> nothing to do
[ -z "$(git status --porcelain)" ] && exit 0

git add -A

# Name the skills that changed, e.g. "edit-video, create-yt-visualizations"
skills=$(git diff --cached --name-only | awk -F/ 'NF>1 && $1 !~ /^\./ {print $1}' | sort -u \
  | sed 's/^ewai-//' | paste -sd ', ' -)
[ -z "$skills" ] && skills="repo"

git commit -q -m "$skills: auto-commit $(date '+%Y-%m-%d %H:%M')" || exit 0

# Push in the background so ending the session isn't held up by the network
nohup git push -q origin HEAD >>"$LOG" 2>&1 &
exit 0
