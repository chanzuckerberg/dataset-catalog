---
name: common-errors
description: Maps exact catalog error text — API responses, catalog-client exceptions, `catalog` CLI messages, generated registration script output, validator lines, and plugin hook blocks — to cause, fix, and the skill that explains it. Use when a catalog command, registration script, or SDK call fails, or when the user pastes an error.
model: sonnet
---

# Common errors

Match on the quoted text (it is the exact string, or its stable prefix). `<…>` is a variable part.
Not listed? Read the full message: the SDK formats HTTP errors as `HTTP <status>: <detail>`, and the
detail is usually specific.

Each table gives cause, fix, and the skill that explains it. Find the row by grepping a distinctive,
non-variable fragment of the message, which returns only the matching row:

```bash
grep -rF 'does not have write permissions' "${CLAUDE_PLUGIN_ROOT}/skills/common-errors/reference"
```

No match, or the fragment is too generic? Read the one table the error's source points to:

| Error source | Table |
|---|---|
| 401, token, URL or environment variables, `whoami`/`check_auth`, `catalog` CLI auth, HTML instead of JSON | `${CLAUDE_PLUGIN_ROOT}/skills/common-errors/reference/access.md` |
| 422, `Field required`, `Input should be …`, `validate_record.py`, unregistrable location, `limit` | `${CLAUDE_PLUGIN_ROOT}/skills/common-errors/reference/validation.md` |
| Duplicate or missing dataset, `DatasetRef` resolution, 404, 400 paging, 409 lineage, 503 search | `${CLAUDE_PLUGIN_ROOT}/skills/common-errors/reference/records.md` |
| Generated script output and exit codes, `Blocked:` hook messages, lint failures, session-start `catalog environment`/`catalog readiness` lines | `${CLAUDE_PLUGIN_ROOT}/skills/common-errors/reference/scripts.md` |
