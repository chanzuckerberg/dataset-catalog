---
description: Diagnose a failed catalog registration, script run, or API call and propose a fix.
argument-hint: [error text | script path | log path]
---
Hand this failure to the `registration-debugger` agent.

1. Collect, without asking for anything already in this conversation: the exact error text or
   log lines, the command that was run (with `--env` and `--dry-run` flags), the script path, and
   its `mapping.json` path. `$ARGUMENTS` may hold any of these. If none of it is available, ask for
   the error text first.
2. Start the agent with that bundle. Never include token values.
3. Relay its diagnosis and proposed fix. Apply the fix only after the user agrees; changes to a
   registration script go to the `script-writer` agent with the existing path.
