---
description: Check which catalog environment you're pointed at and whether your token can read and write.
argument-hint: [--verbose]
disable-model-invocation: true
model: haiku
allowed-tools: Bash(*check_auth.sh*)
---
## Token check
!`"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh" --report $ARGUMENTS`

Summarize the result above in a short table, starting with the environment and URL (from `CATALOG_API_URL`; `unknown` is treated as production). To switch environments, see `catalog-guide`. If write access is missing, search the docs for the access-request process.
If the result above is missing (shell injection disabled), run the same script with Bash.
