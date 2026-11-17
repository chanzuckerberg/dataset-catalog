#!/usr/bin/env bash
# SessionStart(startup): offer onboarding once per user per machine.
MARKER="${CLAUDE_PLUGIN_DATA}/onboarding.json"
[ -f "$MARKER" ] && exit 0
cat <<'EOF'
The user has just enabled the scientific dataset catalog plugin and has not been onboarded.
In your first reply, briefly offer to walk them through onboarding using the onboarding steps in the `catalog-guide` skill
(about 10 minutes, sandbox only). If they accept, run the skill. If they decline, record
{"status":"declined"} in the onboarding marker file and tell them they can run /catalog:onboard any time.
Answer their actual first message as well — don't hijack it.
EOF
# Bash tool commands do not see CLAUDE_PLUGIN_DATA, so hand Claude the resolved path.
printf 'Onboarding marker file: %s\n' "$MARKER"
