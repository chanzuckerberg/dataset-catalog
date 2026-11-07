---
description: Create or change a script that registers your data with the catalog, then dry-run it in staging.
argument-hint: [data path | existing script path]
---
Gather the inputs for a registration script, then hand them to the `script-writer` agent. The agent
cannot ask questions, so collect everything here first. Ask **one question at a time**; skip any
the user has already answered or that `$ARGUMENTS` settles.

1. **Data location and type**: path(s) or URI(s), storage platform (confirm which HPC site), data
   type and file formats. Look at the location read-only (names, counts, sizes) to ground later questions.
2. **Granularity**: propose what one dataset is, using the `concepts` skill's "Is this a dataset?"
   guide, and get the user's confirmation.
3. **Governance**: ask for `is_pii`, `is_phi`, `license`, `data_steward`, and `data_owner`. Never infer
   or default them; "not sure" means it stays unanswered and the script will not register (see
   `registration-script`, governance).
4. **Collections and lineage parents**: search for them (`search` skill), show what you found, and
   confirm each id with the user.
5. **Where it runs**: notebook, cron, Nextflow, Snakemake, Airflow, or by hand.
6. **Output path** for the new script and `mapping.json`, or the existing script path plus the
   change wanted.

Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.py" staging` (the `/catalog:whoami`
check). Show a one-screen summary (location, granularity, N datasets
expected, governance answers, parents, collections, runtime, output path, token status) and ask the
user to confirm. On confirmation, start `script-writer` with that summary as its brief.

When it returns: run the `metadata-reviewer` agent on one payload from `catalog-dry-run/`, show both
reports, and explain how to run for real: `--env staging` first, then `--env prod --dry-run` and
`--env prod` with a production credential.
