#!/usr/bin/env python3
"""Multi-term dataset search: run one pass per term and union the hits by id.

Catalog search matches only the *text that was indexed* — a dataset tagged
"hepatic" will not surface for ``q=liver``. To raise recall you search several
related terms (canonical label, synonyms, subtypes) and union the results by
dataset ``id``. The catalog CLI can't do that in one call, so this script
encapsulates the fan-out + union.

Where do the terms come from? Two paths:

  1. PREFERRED — the agent expands the term with the plugin's ``ols`` MCP server
     (synonyms, subtypes) and passes the results in with ``--terms``. A running
     script is a subprocess and cannot reach the session's MCP connection, so
     expansion has to happen agent-side; this script just consumes the terms.

         # agent resolves "liver" -> liver, hepatic, hepatocyte via the ols MCP, then:
         python search_expanded.py --terms "liver,hepatic,hepatocyte"

  2. FALLBACK — run standalone with ``--q`` and no ``--terms``, and the script
     expands the term itself against the public OLS4 REST API (same EBI service
     the MCP fronts). Use this when there's no agent/MCP in the loop. If OLS is
     unreachable it warns and searches the bare term.

         python search_expanded.py --q liver --ontology uberon --subtypes

Configuration comes from the environment (same as the ``catalog`` CLI):
    CATALOG_API_URL    base URL of the catalog
    CATALOG_API_TOKEN  API token (issue at <catalog>/tokens in a logged-in browser)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from _catalog import (
    DEFAULT_SORT,
    EXIT_ERROR,
    MODALITIES,
    SORTS,
    CatalogError,
    get_client,
    usage_error,
)

OLS_BASE = "https://www.ebi.ac.uk/ols4/api"
OLS_TIMEOUT = 15.0


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _dedup_preserving(terms: list[str], limit: int) -> list[str]:
    """Case-insensitive dedup, preserving first-seen order, capped at ``limit``."""
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(term.strip())
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------- OLS4 REST fallback expansion

# NOTE: this path exists only for standalone runs with no agent/MCP. When an
# agent drives the script it should expand via the `ols` MCP and pass --terms;
# a subprocess cannot reach the session's MCP connection.


def _ols_get(path: str, params: dict[str, Any]) -> dict | None:
    """GET one OLS4 endpoint; return parsed JSON or None on any failure."""
    url = f"{OLS_BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=OLS_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        _warn(f"OLS request failed ({exc}); continuing without it.")
        return None


def _ols_top_class(term: str, ontology: str | None) -> dict | None:
    """Resolve ``term`` to its best-matching OLS class (label, synonyms, iri)."""
    params: dict[str, Any] = {
        "q": term,
        "fieldList": "label,synonym,obo_id,iri,ontology_name",
        "rows": 1,
    }
    if ontology:
        params["ontology"] = ontology.lower()
    data = _ols_get("search", params)
    docs = ((data or {}).get("response") or {}).get("docs") or []
    return docs[0] if docs else None


def _ols_descendants(doc: dict, max_terms: int) -> list[str]:
    """Fetch subtype labels for an OLS class (best-effort, capped)."""
    ontology = doc.get("ontology_name")
    iri = doc.get("iri")
    if not ontology or not iri:
        return []
    # OLS requires the IRI double-URL-encoded in the path segment.
    encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
    data = _ols_get(
        f"ontologies/{ontology}/terms/{encoded}/descendants", {"size": max_terms}
    )
    terms = ((data or {}).get("_embedded") or {}).get("terms") or []
    return [t["label"] for t in terms if t.get("label")]


def _ols_expand(
    term: str, ontology: str | None, subtypes: bool, max_terms: int
) -> list[str]:
    """Return ``term`` plus its OLS label/synonyms (and subtypes if requested)."""
    candidates = [term]
    doc = _ols_top_class(term, ontology)
    if doc is None:
        _warn(f"no OLS match for {term!r}; searching the bare term only.")
        return [term]
    if doc.get("label"):
        candidates.append(doc["label"])
    candidates.extend(doc.get("synonym") or [])
    if subtypes:
        candidates.extend(_ols_descendants(doc, max_terms))
    return _dedup_preserving(candidates, max_terms)


# --------------------------------------------------------------------- searching


def _search_pass(client: Any, term: str, filters: dict, limit: int) -> list:
    return client.datasets.search(q=term, limit=limit, **filters).results


def _union_hits(client: Any, terms: list[str], filters: dict, limit: int) -> list[dict]:
    """Run one search per term; union by dataset id, tracking which terms matched."""
    merged: dict[str, dict] = {}
    for term in terms:
        for hit in _search_pass(client, term, filters, limit):
            row = merged.get(hit.id)
            if row is None:
                merged[hit.id] = {
                    "id": hit.id,
                    "canonical_id": hit.canonical_id,
                    "version": hit.version,
                    "modality": _enum_value(hit.modality),
                    "project": hit.project,
                    "name": hit.name,
                    "score": hit.score,
                    "matched_terms": [term],
                }
            else:
                row["matched_terms"].append(term)
                if hit.score is not None and (
                    row["score"] is None or hit.score > row["score"]
                ):
                    row["score"] = hit.score
    rows = list(merged.values())
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0), r["name"]))
    return rows


# ---------------------------------------------------------------------- rendering


def _truncate(value: Any, width: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no matching datasets)")
        return
    columns = [
        ("canonical_id", "DATASET", 28),
        ("version", "VER", 7),
        ("modality", "MODALITY", 12),
        ("project", "PROJECT", 16),
        ("name", "NAME", 40),
    ]
    headers = [header for _, header, _ in columns]
    cells = [
        [_truncate(row.get(key), width) for key, _, width in columns] for row in rows
    ]
    widths = [len(h) for h in headers]
    for line in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, line)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for line in cells:
        print(fmt.format(*line))


# --------------------------------------------------------------------------- main


def _resolve_terms(args: argparse.Namespace) -> list[str]:
    """Decide the term list: explicit --terms win; else OLS-expand --q (fallback)."""
    explicit: list[str] = []
    if args.q:
        explicit.append(args.q)
    if args.terms:
        explicit.extend(part for part in args.terms.split(",") if part.strip())

    # --terms (or --no-expand) means the caller already chose the terms — no OLS.
    if args.terms or args.no_expand:
        return _dedup_preserving(explicit, args.max_terms)
    # Standalone fallback: expand the single --q term against OLS4 REST.
    return _ols_expand(args.q, args.ontology, args.subtypes, args.max_terms)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="search_expanded",
        description="Multi-term dataset search: run a pass per term, union the hits.",
    )
    parser.add_argument(
        "--terms",
        help="comma-separated terms to search (e.g. from the ols MCP); skips OLS",
    )
    parser.add_argument("--q", help="single base term (OLS-expanded if --terms absent)")
    parser.add_argument(
        "--ontology",
        help="fallback OLS scope for --q (e.g. uberon, cl, efo, mondo)",
    )
    parser.add_argument(
        "--subtypes",
        action="store_true",
        help="fallback: also fan out into the --q term's OLS subtypes",
    )
    parser.add_argument(
        "--no-expand",
        action="store_true",
        help="never call OLS; search --q / --terms verbatim",
    )
    parser.add_argument(
        "--max-terms",
        type=int,
        default=8,
        help="cap on terms searched (default: 8)",
    )
    # Dataset filters, passed through to each search pass.
    parser.add_argument("--modality", choices=MODALITIES)
    parser.add_argument("--project")
    parser.add_argument("--organism")
    parser.add_argument("--tissue")
    parser.add_argument("--assay")
    parser.add_argument("--disease")
    parser.add_argument("--sub-modality")
    parser.add_argument("--development-stage")
    parser.add_argument("--access-scope")
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help="include non-latest dataset versions (default: latest only)",
    )
    parser.add_argument(
        "--sort",
        choices=SORTS,
        default=DEFAULT_SORT,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="max hits fetched per term before union (default: 25)",
    )
    parser.add_argument("-o", "--output", choices=["table", "json"], default=None)
    args = parser.parse_args(argv)

    if not args.q and not args.terms:
        usage_error("give --terms (preferred, from the ols MCP) or --q.")
    if args.max_terms < 1:
        usage_error("--max-terms must be at least 1.")
    if args.no_expand and not args.q and not args.terms:
        usage_error("--no-expand needs --q or --terms to search.")
    if args.output is None:
        args.output = "table" if sys.stdout.isatty() else "json"

    terms = _resolve_terms(args)
    if not terms:
        usage_error("no search terms after expansion.")

    filters: dict[str, Any] = {
        "is_latest": None if args.all_versions else True,
        "sort": args.sort,
    }
    if args.modality:
        filters["modality"] = args.modality
    for key in (
        "project",
        "organism",
        "tissue",
        "assay",
        "disease",
        "sub_modality",
        "development_stage",
        "access_scope",
    ):
        value = getattr(args, key)
        if value is not None:
            filters[key] = value

    try:
        with get_client() as client:
            rows = _union_hits(client, terms, filters, args.limit)
    except CatalogError as exc:
        print(f"error: request failed: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)

    if args.output == "json":
        print(
            json.dumps(
                {"searched_terms": terms, "count": len(rows), "datasets": rows},
                indent=2,
                default=str,
            )
        )
    else:
        print(f"searched terms: {', '.join(terms)}")
        print(f"unioned {len(rows)} distinct datasets\n")
        _print_table(rows)


if __name__ == "__main__":
    main()
