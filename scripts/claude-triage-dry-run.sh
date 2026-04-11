#!/usr/bin/env bash
# claude-triage-dry-run.sh — preview what the Claude: Triage workflow would
# post on an issue, without touching it.
#
# Usage:
#   scripts/claude-triage-dry-run.sh <issue-number>
#   REPO=Oddly/elasticstack scripts/claude-triage-dry-run.sh 121
#
# Runs claude-code locally in print mode (-p) against the SAME prompt the
# production workflow uses (.github/prompts/triage.md), seeded with the issue
# metadata pulled from gh. Claude has read-only access to the repo and to gh
# issue/search/api. It writes its proposed comment to stdout and exits.
#
# Nothing is posted to the issue. This is strictly a client-side preview.
#
# Requirements:
#   - claude CLI on PATH, authenticated (subscription or CLAUDE_CODE_OAUTH_TOKEN)
#   - gh CLI on PATH, authenticated for the target repo
#   - Run from inside a checkout of the repo (so Claude can grep/read files)

set -euo pipefail

issue_number="${1:?usage: $0 <issue-number>}"
repo="${REPO:-Oddly/elasticstack}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
prompt_file="$repo_root/.github/prompts/triage.md"

if [[ ! -f "$prompt_file" ]]; then
    echo "error: prompt file not found at $prompt_file" >&2
    exit 1
fi

# Claude needs to read/grep the repo from its root for the triage to be
# code-grounded. Anchor cwd here regardless of where the user invoked us.
cd "$repo_root"

command -v claude >/dev/null || { echo "error: claude CLI not on PATH" >&2; exit 1; }
command -v gh     >/dev/null || { echo "error: gh CLI not on PATH"     >&2; exit 1; }

issue_json=$(gh issue view "$issue_number" --repo "$repo" \
    --json number,title,body,labels,author,createdAt,state) \
    || { echo "error: could not fetch issue #$issue_number from $repo" >&2; exit 1; }

# Build the same prompt the workflow builds, plus an explicit "dry run, do not
# try to post" directive so claude doesn't attempt gh issue comment.
prompt=$(mktemp)
trap 'rm -f "$prompt"' EXIT
{
    cat "$prompt_file"
    echo
    echo "Issue to triage: #$issue_number"
    echo
    echo "--- dry-run mode ---"
    echo "This is a client-side preview. Write the triage comment to stdout"
    echo "as plain Markdown. Do NOT invoke 'gh issue comment' or any other"
    echo "tool that would post to GitHub."
    echo
    echo "Issue metadata (from gh issue view --json):"
    echo '```json'
    echo "$issue_json"
    echo '```'
} > "$prompt"

echo "==> Dry-running triage for $repo#$issue_number" >&2
echo "==> Prompt: $prompt_file" >&2
echo "==> Claude will have read access to the repo and read-only gh/git tools." >&2
echo "==> Nothing will be posted." >&2
echo >&2

claude -p \
    --model claude-sonnet-4-20250514 \
    --allowedTools 'Read,Grep,Glob,Bash(git:*),Bash(gh issue view:*),Bash(gh search:*),Bash(gh api repos/'"${repo}"'/contents/*)' \
    < "$prompt"
