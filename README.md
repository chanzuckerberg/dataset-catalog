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
New to the catalog, or registering data from a pipeline? Install the `catalog` plugin for guided onboarding and registration scripts.
→ **[Installation](#claude-code-plugin)**

### 🔧 **Contributing**
Want to contribute to the codebase?
→ **[Development Guide](dataset-catalog-client/README.md#installation)**

## Claude Code Plugin

This repo ships a Claude Code plugin, `catalog`, distributed through the `dataset-catalog` marketplace defined in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json). It helps a scientist with no catalog experience understand the catalog, map their data onto it, write correct metadata, and register data from code that runs in their own pipeline. Claude writes the registration script; you own it and run it. Nothing in the plugin registers data on its own.

### What it does

| Component | Type | What it's for |
| --- | --- | --- |
| `onboard` | skill | First-run guide: asks what you want to do, checks your setup, explains the catalog in your terms, and gets you to one success in staging. Offered automatically on your first session. |
| `concepts` | skill | Datasets, assets, lineage, collections, and how to decide what one dataset is. |
| `field-reference` | skill | Every record field: type, required, allowed values, meaning, examples by data type. Generated from the client models and the API spec. |
| `registration-script` | skill | How to produce correct records from code: order of operations, checksums, governance decisions, the pipeline-safety rules, and the script template. |
| `search` | skill | Finding data: search, facets, exact lookups, resolving a file path to its dataset, lineage, collections. |
| `auth` | skill | Tokens per environment, read/write permission, pipeline credentials, rotation. |
| `common-errors` | skill | Exact error text → cause → fix. |
| `script-writer` | agent | Writes or changes a registration script from the template and dry-runs it in staging. |
| `metadata-reviewer` | agent | Read-only review of a draft record; returns blocking issues and warnings. |
| `registration-debugger` | agent | Diagnoses a failed registration and proposes a fix. |
| hooks | hooks | Session start: onboarding offer and a readiness check (silent unless something is wrong). Before tool use: blocks a production registration run without a passing production dry run, blocks writing a literal API token into a file, and auto-approves read-only catalog commands. After writes: lints generated scripts against the pipeline-safety rules. |

### Commands

| Command | Does |
| --- | --- |
| `/catalog:onboard` | Starts the onboarding guide. |
| `/catalog:register [path]` | Asks about your data one question at a time, then has `script-writer` produce a script and dry-run it in staging. |
| `/catalog:validate <file>` | Validates a draft record (JSON) or lints a registration script. |
| `/catalog:debug [error]` | Hands a failure to `registration-debugger`. |
| `/catalog:whoami [env]` | Shows environment, identity, read/write permission, and token expiry. Never prints the token. |

### Prerequisites

- Python 3.11+ (`python3` on your `PATH`; the plugin's own scripts need nothing else).
- For registration scripts and the `catalog` CLI: `catalog-client` 1.3.0 or newer, installed from a release tag (the `registration-script` skill has the steps).
- A token per environment, set in your Claude Code environment settings or shell (never typed into chat). Variable names are in [`.env.example`](.env.example):

```text
CATALOG_STAGING_API_TOKEN   staging token — the plugin defaults to staging everywhere
CATALOG_PROD_API_TOKEN      production token — give this to your production pipeline, not to Claude Code
CATALOG_API_URL / CATALOG_API_TOKEN   the pair the catalog CLI and SDK examples read
```

Issue tokens at `<catalog URL>/tokens` in a logged-in browser.

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
```

**Installed mid-session?** Run `/reload-plugins` to load the skills, commands, agents, and hooks now. The onboarding offer comes from a session-start hook, so it appears at the start of your **next** session (or run `/catalog:onboard` right away). Confirm with `claude plugin list`. Organisation-managed settings can disable plugin hooks; the skills and commands still work without them.

### Update

From inside a Claude Code session:

```
/plugin marketplace update dataset-catalog
/plugin        # opens the plugin menu — pick "Update" for catalog@dataset-catalog
```

Or from your terminal:

```bash
claude plugin marketplace update dataset-catalog
claude plugin update catalog@dataset-catalog
```

`marketplace update` pulls the latest marketplace definition; `plugin update` (or the `/plugin` menu) upgrades `catalog@dataset-catalog` to the newest published version. Run `/reload-plugins` inside a session to apply it (a new session picks it up automatically). Your onboarding status survives updates; uninstalling the plugin removes it. Plugin versions are managed by release-please — see the plugin [CHANGELOG](plugins/catalog/CHANGELOG.md).

### Keep production credentials out of Claude Code

A plugin cannot ship permission rules, so add deny rules to your project's `.claude/settings.json` (or your user settings) to keep Claude from reading or using production credentials. Adjust paths to where you keep secrets, and check the result with `/permissions`:

```json
{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Bash(printenv *)",
      "Bash(env)",
      "Bash(*CATALOG_PROD_API_TOKEN*)",
      "Bash(*--env prod*)",
      "Bash(*--env=prod*)"
    ]
  }
}
```

With these, Claude can dry-run and register in staging, and production runs happen in your pipeline with `CATALOG_PROD_API_TOKEN` from its secrets store.

### Developing the plugin

```bash
cd plugins/catalog
python3 -m unittest discover -s tests -t tests      # stdlib only; CI runs the same
```

At each plugin release, regenerate the field reference with the Python that has the released `catalog-client` installed, and commit the result. It reads the API spec from `CATALOG_API_URL` (staging when unset) with `CATALOG_API_TOKEN`:

```bash
python plugins/catalog/skills/field-reference/scripts/generate.py
```

Hand edits go in `skills/field-reference/examples.json` only; `fields/*.md` and `fields.json` are generated.

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
