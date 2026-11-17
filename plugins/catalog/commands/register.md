---
description: Create or change a script that registers your data with the catalog, then dry-run it against a dev or staging catalog.
argument-hint: [data path | existing script path]
---
Gather the inputs for a registration script, then hand them to the `script-writer` agent. The agent
cannot ask questions, so collect everything here first. Ask **one question at a time**; skip any
the user has already answered or that `$ARGUMENTS` settles.

1. **Data location and type**: path(s) or URI(s) on shared organization storage, storage platform
   (confirm which HPC site), data type and file formats. If the data is on a local disk or in
   personal storage, stop: explain the shared-storage rule (`catalog-guide`, rules) and continue only
   once it is on shared storage. Look at the location read-only (names, counts, sizes) to ground later questions.
   Settle each file format by the File format rules (`registration-script` reference `fields.md`):
   if the session is not pointed at prod, ask the user to paste
   `catalog facets --fields file_format --all-versions` run against prod.
2. **Granularity**: propose what one dataset is, using the docs' "Is this a dataset?" guide, and get
   the user's confirmation.
3. **Governance**: ask for `is_pii`, `is_phi`, `license`, `data_steward`, and `data_owner`. Never infer
   or default them; "not sure" means it stays unanswered and the script will not register (see
   `registration-script`, governance).
4. **Collections and lineage parents**: search for them (`registration-script`, search patterns), show what you found, and
   confirm each id with the user.
5. **Where it runs**: notebook, cron, Nextflow, Snakemake, Airflow, or by hand.
6. **Output path** for the new script and `mapping.json`, or the existing script path plus the
   change wanted.

Then run `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` (the `/catalog:whoami` check) and
tell the user the environment it names. If it is `prod` or `unknown`, ask them to point
`CATALOG_API_URL`/`CATALOG_API_TOKEN` at a dev or staging catalog for the trial (`catalog-guide`) and
rerun the check. Show a one-screen summary (location, granularity, N datasets expected, governance
answers, parents, collections, runtime, output path, environment and URL, token status) and ask the
user to confirm. On confirmation, start `script-writer` with that summary as its brief.

When it returns: run the `metadata-reviewer` agent on one payload from `catalog-dry-run/`, show both
reports, and explain how to run for real: a real run against the dev or staging catalog first, then, with
`CATALOG_API_URL`/`CATALOG_API_TOKEN` pointed at prod (a production credential, usually in their
pipeline), `--dry-run` and then the real run. After every real run, show the user the `Search page`
link(s) the script prints (`registration-script`, verify).
