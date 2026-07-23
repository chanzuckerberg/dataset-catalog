# Scientific Dataset Catalog

Managing scientific datasets, their relationships, and metadata across research workflows can be complex and error-prone. The Scientific Dataset Catalog provides a centralized system for tracking datasets, their lineage, collections, and rich metadata throughout the research lifecycle.

This system helps you organize datasets into collections, track how datasets relate to each other (lineage relationships), store rich metadata, and provides a Python client for programmatic access to all these capabilities.

## Getting Started

### 🐍 **Using the Python Client**
Want to integrate dataset catalog functionality into your Python workflows?
→ **[Quick Start](dataset-catalog-client/README.md#quick-start)** | **[Full Documentation](dataset-catalog-client/USAGE.md)**

### 📋 **Understanding the Data Schema**
Want to understand dataset metadata structure and relationships?
→ **[Schema Documentation](schema/README.md)**

### 🤖 **Claude Code Plugin**
Prefer to work in Claude Code? Install the `catalog` plugin.
→ **[Installation](#claude-code-plugin)**

### 🔧 **Contributing**
Want to contribute to the codebase?
→ **[Development Guide](dataset-catalog-client/README.md#installation)**

## Claude Code Plugin

This repo ships a Claude Code plugin, `catalog`, distributed through the `dataset-catalog` marketplace defined in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json). It lets you register, read, and search the Scientific Dataset Catalog conversationally from a Claude Code session — no client install required for the common read paths.

### What it does

The plugin adds three skills, a read-only subagent, an ontology MCP server, and a safety hook:

| Component | Type | What it's for |
| --- | --- | --- |
| `catalog-register` | skill | Maps your dataset metadata onto the latest catalog schema and generates a runnable registration script. This is the only **write** path. |
| `catalog-read` | skill | Read-only lookups and analysis — get a dataset by UUID or canonical ID, list a project, browse collections, discover facet values, trace lineage, and aggregate, compare, or **visualize** across results. The everyday default. |
| `catalog-search` | skill | High-recall search that expands a term through synonyms and the OLS ontology hierarchy, then unions the hits by dataset id — so a dataset tagged "hepatic" still surfaces for a "liver" query. Higher overhead; use when recall matters. |
| `catalog-reader` | subagent | Runs multi-page reads and fan-out searches in its own context and returns only the distilled answer, keeping paginated JSON out of the main conversation. |
| `ols` | MCP server | Read-only access to the [EBI OLS4](https://www.ebi.ac.uk/ols4/) ontology service, used by `catalog-search` for term expansion. |
| read hook | PreToolUse hook | Auto-approves read-only catalog/OLS commands so bounded reads run without a prompt. All catalog access stays `GET`-only; writes go only through `catalog-register`. |

`catalog-read` and `catalog-search` share a single read-only operating contract (`plugins/catalog/reference/read-contract.md`): every catalog and OLS call is a `GET`, and the API token travels only as the `X-catalog-api-token` header.

### Prerequisites

Set these in your Claude Code environment settings before using the plugin (the token is read from the environment, never entered in chat):

```text
CATALOG_API_TOKEN   API token; required — issue one at <base_url>/tokens (SSO-gated)
CATALOG_API_URL     base URL; optional, defaults to production when unset
```

### Install

From inside a Claude Code session:

```
/plugin marketplace add chanzuckerberg/dataset-catalog
/plugin install catalog@dataset-catalog
```

Or from your terminal (outside a session):

```bash
claude plugin marketplace add chanzuckerberg/dataset-catalog
claude plugin install catalog@dataset-catalog
# then, inside a Claude Code session, apply it:
#   /reload-plugins
```

**Reload after installing.** If you're already inside a Claude Code session, run `/reload-plugins` to load the skills, `catalog-reader` subagent, `ols` MCP server, and read hook. (A new session picks them up automatically.) Confirm with `claude plugin list`.

### Update

From inside a Claude Code session:

```
/plugin marketplace update dataset-catalog
/plugin
```

Or from your terminal:

```bash
claude plugin marketplace update dataset-catalog
claude plugin update catalog@dataset-catalog
# then, inside a Claude Code session, apply it:
#   /reload-plugins
```

`marketplace update` pulls the latest marketplace definition; `plugin update` (or the `/plugin` menu) upgrades `catalog@dataset-catalog` to the newest published version. **Reload after updating** — if you're inside a session, run `/reload-plugins` to apply the new version (a new session picks it up automatically). Plugin versions are managed by release-please — see the plugin [CHANGELOG](plugins/catalog/CHANGELOG.md).

## Quick Start

Ready to start using the Python client? The fastest way to get up and running:

→ **[Installation & Quick Start Guide](dataset-catalog-client/README.md#quick-start)**

This will walk you through installation, getting an API token, and your first few API calls.

## Documentation & Resources

### 📚 **Complete Documentation**
- **[Python Client Usage Guide](dataset-catalog-client/USAGE.md)** - Comprehensive guide covering datasets, collections, lineage, async usage, and error handling
- **[Interactive Examples](dataset-catalog-client/examples/)** - Jupyter notebooks with step-by-step walkthroughs
- **[API Token Setup](dataset-catalog-client/README.md#getting-an-api-token)** - How to generate and use API tokens

### 🔗 **Related Projects**
- **Dataset Catalog API** - The backend service this client connects to
- **[Schema Documentation](schema/README.md)** - Detailed data models and relationships

### 🤝 **Contributing**
- **[Development Setup](dataset-catalog-client/README.md)** - Local development and testing
- **[Issues & Feedback](https://github.com/chanzuckerberg/dataset-catalog/issues)** - Report bugs or request features

## Code of Conduct

This project adheres to the Contributor Covenant [code of conduct](https://github.com/chanzuckerberg/.github/blob/master/CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to [opensource@chanzuckerberg.com](mailto:opensource@chanzuckerberg.com).
