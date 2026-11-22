#!/bin/bash
# Install the TypeScript LSP plugin and its language server in Claude Code cloud sessions.
set -euo pipefail

# Only run in remote (cloud) sessions; local machines manage their own plugins.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

claude plugin marketplace add anthropics/claude-plugins-official || true
claude plugin install typescript-lsp@claude-plugins-official

if ! command -v typescript-language-server >/dev/null 2>&1; then
  npm i -g typescript-language-server typescript
fi
