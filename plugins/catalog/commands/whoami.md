---
description: Check which catalog environment you're pointed at and whether your token can read and write.
argument-hint: [env]
disable-model-invocation: true
model: haiku
allowed-tools: Bash(python3 *check_auth.py*)
---
## Token check
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.py" --report $ARGUMENTS`

Summarize the result above in a short table. If write access is missing, point to the auth skill's access-request steps.
If the result above is missing (shell injection disabled), run the same script with Bash.
