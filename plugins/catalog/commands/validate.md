---
description: Validate a draft catalog record (JSON) or lint a registration script before registering.
argument-hint: <record.json | register.py> [--model dataset|asset|collection|lineage]
allowed-tools: Bash(python3 *validate_record.py*), Bash(python3 *lint_registration_script.py*)
---
Validate `$ARGUMENTS`.

- A `.json` record: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_record.py" $ARGUMENTS`.
  Dataset records are the default; pass `--model` for an asset, collection, or lineage edge.
- A `.py` registration script: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lint_registration_script.py" <path>`,
  then validate any payloads its last dry run wrote to `catalog-dry-run/` the same way.
- No path given: ask which file.

Report the result as-is: `valid`/`ok`, or each `<path>: <message>` line. For each problem, cite the
`field-reference` entry (or the `registration-script` rule) and say what to change; do not edit the
file unless the user asks. For a deeper review of a valid record, offer the `metadata-reviewer` agent.
