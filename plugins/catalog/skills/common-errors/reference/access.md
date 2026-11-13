# Access

| Error text | Cause | Fix | See |
|---|---|---|---|
| `Missing required header: X-catalog-api-token` (401) | Request sent without the token header | Send `X-catalog-api-token: <token>`; not `Authorization: Bearer` | auth |
| `Invalid or expired token` (401) | Token expired, revoked, mistyped, or for another environment | Issue a new token for this environment; check the variable with `/catalog:whoami` | auth |
| `does not have write permissions` | Not in the `sci-data-curation` team, or token issued before joining it | Request the team in Okta, then issue a new token | auth |
| An HTML page (`<!DOCTYPE html>`) instead of JSON | Request missed the header or hit a non-`/api/` path, so the SSO proxy answered | Use `/api/v1/...` paths with the header | search |
| `set CATALOG_API_URL and CATALOG_API_TOKEN for the catalog to register into` (script exit 2; names only the missing one when one is set) | The generated script has no catalog to target; there is no default | Export the pair for a dev or staging catalog first | auth |
| `check_auth: CATALOG_API_URL is not set, so there is no catalog to check.` (whoami, exit 2) | No catalog URL in the environment | Export `CATALOG_API_URL` and `CATALOG_API_TOKEN`, then rerun | auth |
| `none — set CATALOG_API_TOKEN for this catalog` (whoami `token source`, exit 2) | URL set, token not | Export the token for that catalog | auth |
| `unknown — CATALOG_API_URL names no dev/staging/prod host; treated as production` (whoami `environment`) | The URL's host names no environment | Not an error; production rules apply. Check the URL is the catalog you meant | auth |
| `check_auth: could not reach <url> (<environment>): <reason>. Check network/VPN.` (whoami, exit 1) | Network, VPN, or a wrong URL | Check VPN and the URL | auth |
| `error: set CATALOG_API_URL and CATALOG_API_TOKEN in the environment.` (CLI exit 2) | The CLI reads only the generic pair | Export both | auth |
| `authentication failed — check CATALOG_API_TOKEN: HTTP 401: …` (CLI exit 3) | As the 401 rows above | As above | auth |
| `write: unknown — needs /api/v1/token/validate` (whoami) | Deployment predates the token-validate route | Not an error; write is unconfirmed | auth |
