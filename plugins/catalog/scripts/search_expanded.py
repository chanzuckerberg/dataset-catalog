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
     the MCP fronts). Use this when there's no agent/MCP in the loop. Beyond label
     + synonyms, opt into hierarchy: ``--children`` (immediate subtypes),
     ``--subtypes`` (full descendant subtree), ``--ancestors`` (broader terms).
     If OLS is unreachable it warns and searches the bare term.

         python search_expanded.py --q liver --ontology uberon --children --ancestors

Two precision refinements layer on top of the fan-out:

  * ``--facet-union FIELD`` — search each term as an exact **facet** value on
    FIELD (e.g. ``tissue``) instead of free-text ``q=``. Union over ontology
    sub-terms this way (a liver's lobes, resolved with ``ols.py``): exact facet
    matches are far more precise than OR-tokenized free text.

        python search_expanded.py --facet-union tissue \
            --terms "liver,caudate lobe of liver,right lobe of liver" --modality sequencing

  * ``--overlap-facet FIELD=VALUE`` — after the union, report how many hits also
    fall in a base bucket (e.g. ``tissue=liver``) and print base + added-only, so
    a "5862 liver + 24 broadened" headline is exact instead of assuming the two
    sets are disjoint. The base bucket is counted, never paginated.

        python search_expanded.py --terms "hepatic,hepatocyte" \
            --modality sequencing --overlap-facet tissue=liver

Configuration comes from the environment (same as the ``catalog`` CLI):
    CATALOG_API_URL    base URL of the catalog
    CATALOG_API_TOKEN  API token (issue at <catalog>/tokens in a logged-in browser)
"""

from __future__ import annotations

import argparse
import json
import sys
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
from ols import related_labels as ols_related
from ols import top_class as ols_top_class


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
# agent drives the script it should expand via the `ols` MCP (or run `ols.py`
# directly) and pass --terms; a subprocess cannot reach the session's MCP
# connection. The OLS4 REST calls themselves live in the `ols` handler module;
# here we only apply the expansion *policy* (which relations to union).


def _ols_expand(
    term: str,
    ontology: str | None,
    subtypes: bool,
    children: bool,
    ancestors: bool,
    max_terms: int,
) -> list[str]:
    """Return ``term`` plus its OLS label/synonyms, and — if requested — its
    immediate children, full subtype subtree, and/or broader ancestors."""
    candidates = [term]
    doc = ols_top_class(term, ontology)
    if doc is None:
        _warn(f"no OLS match for {term!r}; searching the bare term only.")
        return [term]
    if doc.get("label"):
        candidates.append(doc["label"])
    candidates.extend(doc.get("synonyms") or [])
    if children:
        candidates.extend(ols_related(doc, "children", max_terms))
    if subtypes:
        candidates.extend(ols_related(doc, "descendants", max_terms))
    if ancestors:
        broader = ols_related(doc, "ancestors", max_terms, drop_upper=True)
        if broader:
            _warn(
                "ancestors broaden recall at the cost of precision; drop generic "
                "single-word terms before searching (they match unrelated records)."
            )
        candidates.extend(broader)
    return _dedup_preserving(candidates, max_terms)


# --------------------------------------------------------------------- searching

# Facet dimensions the API matches exactly against a controlled vocabulary. A
# union or overlap pass may key on any of these instead of free-text `q=`.
FACET_FIELDS = (
    "modality",
    "project",
    "organism",
    "tissue",
    "assay",
    "disease",
    "sub_modality",
    "development_stage",
    "access_scope",
)


# Set true by _search_pass whenever a pass fills --limit. A union or overlap
# built on a truncated pass can undercount, so any total derived from it is
# unverified — surfaced in the output alongside the count. Reset at each main().
_truncated = False


def _search_pass(client: Any, term: str, field: str, filters: dict, limit: int) -> list:
    """One search pass keyed on ``field`` (``q`` for free-text, else a facet).

    Warns (and flags the run unverified) when the pass fills ``limit`` exactly:
    that almost certainly means the hits were truncated, so a union or overlap
    built on them silently undercounts — the failure mode behind an unverified
    "N + M" total.
    """
    results = client.datasets.search(**{field: term}, limit=limit, **filters).results
    if len(results) >= limit:
        global _truncated
        _truncated = True
        _warn(
            f"{field}={term!r} filled --limit ({limit}); the pass is likely "
            "truncated, so the union/overlap can undercount. Raise --limit."
        )
    return results


def _union_hits(
    client: Any, terms: list[str], field: str, filters: dict, limit: int
) -> list[dict]:
    """Run one search per term (keyed on ``field``); union by dataset id, tracking
    which terms matched."""
    merged: dict[str, dict] = {}
    for term in terms:
        for hit in _search_pass(client, term, field, filters, limit):
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


def _id_set(rows: list[dict]) -> set[str]:
    return {row["id"] for row in rows}


def _term_contributions(rows: list[dict], terms: list[str]) -> dict[str, int]:
    """How many datasets each term contributed. A 0 flags a facet value that isn't
    in the vocabulary (or genuinely empty); an implausibly high one flags a filter
    the API silently ignored."""
    counts: dict[str, int] = dict.fromkeys(terms, 0)
    for row in rows:
        for term in row["matched_terms"]:
            counts[term] = counts.get(term, 0) + 1
    return counts


def _facet_total(client: Any, field: str, value: str, filters: dict) -> int:
    """Total datasets matching a facet value under the shared filters (count only —
    reads the ``total`` field, never paginates the bucket)."""
    return client.datasets.search(**{field: value}, limit=1, **filters).total


def _overlap_report(
    client: Any,
    terms: list[str],
    field: str,
    filters: dict,
    limit: int,
    of_field: str,
    of_value: str,
    broadened_ids: set[str],
) -> dict:
    """Measure how the broadened union overlaps a base facet bucket, so a
    "base + added" total is exact rather than assumed-disjoint.

    base bucket = ``of_field=of_value`` under the shared filters (count only);
    overlap = broadened datasets that ALSO fall in that bucket (re-run the passes
    with the base facet added — the intersection is small, so this is cheap);
    added-only = broadened − overlap; grand total = base + added-only.
    """
    base_total = _facet_total(client, of_field, of_value, filters)
    overlap_rows = _union_hits(
        client, terms, field, {**filters, of_field: of_value}, limit
    )
    overlap_ids = _id_set(overlap_rows) & broadened_ids
    added_ids = broadened_ids - overlap_ids
    return {
        "base_facet": f"{of_field}={of_value}",
        "base_total": base_total,
        "broadened_unique": len(broadened_ids),
        "overlap_with_base": len(overlap_ids),
        "added_only": len(added_ids),
        "grand_total": base_total + len(added_ids),
        # true if any union or overlap pass filled --limit: added_only (and thus
        # grand_total) can then over-count, so the total is not exact.
        "unverified": _truncated,
    }


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
    if args.terms:
        # --terms is the explicit, already-chosen list; it takes precedence over --q.
        if args.q:
            _warn("--terms supplied; ignoring --q (--terms is the explicit term list).")
        explicit = [part.strip() for part in args.terms.split(",") if part.strip()]
    else:
        explicit = [args.q] if args.q else []

    # --terms (or --no-expand) means the caller already chose the terms — no OLS.
    if args.terms or args.no_expand:
        distinct = _dedup_preserving(explicit, len(explicit))
        if len(distinct) > args.max_terms:
            _warn(
                f"{len(distinct)} distinct terms given but --max-terms is "
                f"{args.max_terms}; searching only the first {args.max_terms} "
                f"({', '.join(distinct[: args.max_terms])}). "
                "Raise --max-terms to search them all."
            )
        return distinct[: args.max_terms]
    # Standalone fallback: expand the single --q term against OLS4 REST.
    return _ols_expand(
        args.q,
        args.ontology,
        args.subtypes,
        args.children,
        args.ancestors,
        args.max_terms,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="search_expanded",
        description="Multi-term dataset search: run a pass per term, union the hits.",
    )
    parser.add_argument(
        "--terms",
        help="comma-separated terms to search (e.g. from the ols MCP); skips OLS",
    )
    parser.add_argument(
        "--q", help="single base term, OLS-expanded (ignored if --terms is given)"
    )
    parser.add_argument(
        "--ontology",
        help="fallback OLS scope for --q (e.g. uberon, cl, efo, mondo)",
    )
    parser.add_argument(
        "--children",
        action="store_true",
        help="fallback: also fan out into the --q term's immediate OLS children "
        "(direct subtypes, one level down)",
    )
    parser.add_argument(
        "--subtypes",
        action="store_true",
        help="fallback: also fan out into the --q term's OLS subtypes "
        "(full descendant subtree)",
    )
    parser.add_argument(
        "--ancestors",
        action="store_true",
        help="fallback: also fan out into the --q term's OLS ancestors (broader "
        "terms; best only when --q is already super granular — for a broad term "
        "the ancestors are generic; raises recall but lowers precision)",
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
    parser.add_argument(
        "--facet-union",
        metavar="FIELD",
        help="search each term as an exact FACET value on FIELD (e.g. tissue) "
        "instead of free-text q=; union over ontology sub-terms this way for "
        f"precision. FIELD: {', '.join(FACET_FIELDS)}",
    )
    parser.add_argument(
        "--overlap-facet",
        metavar="FIELD=VALUE",
        help="after the union, report how many hits also fall in the base bucket "
        "FIELD=VALUE (e.g. tissue=liver) and print base + added-only, so a "
        "'base + broadened' total is exact instead of assumed-disjoint",
    )
    parser.add_argument("-o", "--output", choices=["table", "json"], default=None)
    args = parser.parse_args(argv)

    global _truncated
    _truncated = False  # reset per run; _search_pass flips it on a filled --limit

    if not args.q and not args.terms:
        usage_error("give --terms (preferred, from the ols MCP / ols.py) or --q.")
    if args.max_terms < 1:
        usage_error("--max-terms must be at least 1.")
    if args.no_expand and not args.q and not args.terms:
        usage_error("--no-expand needs --q or --terms to search.")
    if args.output is None:
        args.output = "table" if sys.stdout.isatty() else "json"

    # Which key each pass searches on: free-text q= by default, else a facet field.
    union_field = "q"
    if args.facet_union:
        union_field = args.facet_union.replace("-", "_")
        if union_field not in FACET_FIELDS:
            usage_error(
                f"--facet-union FIELD must be one of {', '.join(FACET_FIELDS)}; "
                f"got {args.facet_union!r}."
            )

    overlap_target: tuple[str, str] | None = None
    if args.overlap_facet:
        if "=" not in args.overlap_facet:
            usage_error("--overlap-facet must be FIELD=VALUE, e.g. tissue=liver.")
        of_field, of_value = args.overlap_facet.split("=", 1)
        of_field = of_field.strip().replace("-", "_")
        of_value = of_value.strip()
        if of_field not in FACET_FIELDS:
            usage_error(
                f"--overlap-facet FIELD must be one of {', '.join(FACET_FIELDS)}; "
                f"got {of_field!r}."
            )
        if not of_value:
            usage_error("--overlap-facet needs a non-empty VALUE (FIELD=VALUE).")
        if of_field == union_field:
            usage_error(
                f"--overlap-facet FIELD cannot equal --facet-union FIELD ({of_field})."
            )
        overlap_target = (of_field, of_value)

    # Shared filters applied to every pass; the union field (and any overlap field)
    # are driven by the term list / overlap arg, not set statically here.
    filters: dict[str, Any] = {
        "is_latest": None if args.all_versions else True,
        "sort": args.sort,
    }
    for key in FACET_FIELDS:
        value = getattr(args, key)
        if value is None:
            continue
        if key == union_field:
            _warn(
                f"--{key.replace('_', '-')} ignored: it is the --facet-union field, "
                "whose values come from --terms/--q."
            )
            continue
        if overlap_target and key == overlap_target[0]:
            usage_error(
                f"--{key.replace('_', '-')} conflicts with --overlap-facet "
                f"{overlap_target[0]}=…; the base bucket already sets that field."
            )
        filters[key] = value

    # One client for the whole run: entering the context resolves config
    # (CATALOG_API_URL/TOKEN) exactly once and fails fast — before any OLS work.
    try:
        with get_client() as client:
            terms = _resolve_terms(args)
            if not terms:
                usage_error("no search terms after expansion.")
            rows = _union_hits(client, terms, union_field, filters, args.limit)
            union_unverified = _truncated  # captured before overlap adds its passes
            overlap = (
                _overlap_report(
                    client,
                    terms,
                    union_field,
                    filters,
                    args.limit,
                    overlap_target[0],
                    overlap_target[1],
                    _id_set(rows),
                )
                if overlap_target
                else None
            )
    except CatalogError as exc:
        print(f"error: request failed: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)

    contributions = _term_contributions(rows, terms)

    if args.output == "json":
        payload: dict[str, Any] = {
            "union_field": union_field,
            "searched_terms": terms,
            "term_hits": contributions,
            "count": len(rows),
            # a pass filled --limit: the union undercounts, so count is not exact.
            "count_unverified": union_unverified,
            "datasets": rows,
        }
        if overlap is not None:
            payload["overlap"] = overlap
        print(json.dumps(payload, indent=2, default=str))
    else:
        keyed = "free-text q=" if union_field == "q" else f"facet {union_field}="
        print(f"searched {keyed} terms: {', '.join(terms)}")
        print(
            "per-term hits: "
            + ", ".join(f"{term} ({contributions[term]})" for term in terms)
        )
        union_note = (
            "  [unverified: a pass filled --limit; raise --limit]"
            if union_unverified
            else ""
        )
        print(f"unioned {len(rows)} distinct datasets{union_note}")
        if overlap is not None:
            grand_note = "  [unverified]" if overlap["unverified"] else ""
            print(
                f"\nbase bucket {overlap['base_facet']}: {overlap['base_total']}\n"
                f"  overlap with base:        {overlap['overlap_with_base']}\n"
                f"  added by broadening:      {overlap['added_only']}\n"
                f"  grand total (base+added): {overlap['grand_total']}{grand_note}"
            )
        print()
        _print_table(rows)


if __name__ == "__main__":
    main()
