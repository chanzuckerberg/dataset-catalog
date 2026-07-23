#!/usr/bin/env python3
"""Standalone handler for the EBI Ontology Lookup Service (OLS4).

Four operations, a 1:1 replacement for the `ols` MCP tools the agent otherwise
calls:

  * ``search`` (searchClasses) — resolve a free-text term to ontology classes
    (canonical **label + synonyms + id**).
  * ``children`` (getChildren) — a class's direct children: ``is-a`` subtypes by
    default, or ``--hierarchical`` to also include part-of / develops-from.
  * ``descendants`` (getDescendants) — the full subtype subtree.
  * ``ancestors`` (getAncestors) — broader parent terms (generic upper-ontology
    roots dropped by default; ``--include-upper`` keeps them).

Why this exists as its own script: calling the ``ols`` MCP puts the *entire*
OLS response (~20 fields per hit, scores, ``_links`` …) into the caller's
context. This handler parses each response down to the few fields that matter
and prints only those, so the full payload never lands in the conversation — and
because it's a plain subprocess (no session MCP connection), it also runs inside
the ``catalog-reader`` subagent, which the MCP cannot reach.

Uses the Python standard library only — no install, same posture as the other
bundled scripts. ``search_expanded.py`` imports :func:`top_class` /
:func:`related_labels` from here for its fallback expansion, so the OLS calls
live in exactly one place.

    python ols.py search liver --ontology uberon
    python ols.py children UBERON:0002107 --ontology uberon --hierarchical
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

OLS_BASE = "https://www.ebi.ac.uk/ols4/api"
OLS_TIMEOUT = 15.0

# Fields requested from the search endpoint — everything the distilled row needs
# and nothing else, so the response is small even before we parse it.
_SEARCH_FIELDS = "label,synonym,obo_id,iri,ontology_name"

# OLS4 term sub-resources usable as a "children" relation.
RELATIONS = ("children", "hierarchicalChildren", "descendants", "ancestors")


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


# ------------------------------------------------------------------- HTTP + parse


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


def _distill(doc: dict) -> dict:
    """Keep only the fields callers need; drop the rest of the OLS payload.

    This projection is the whole point of the handler — it is where a
    multi-kilobyte OLS document becomes a handful of fields. ``iri`` and
    ``ontology_name`` are retained (not just for display) so a search result can
    be fed straight into :func:`get_children` without a second lookup.
    """
    synonyms = doc.get("synonym") or doc.get("synonyms") or doc.get("obo_synonym") or []
    description = doc.get("description")
    if isinstance(description, list):
        description = description[0] if description else None
    return {
        "obo_id": doc.get("obo_id"),
        "label": doc.get("label"),
        "iri": doc.get("iri"),
        "ontology_name": doc.get("ontology_name"),
        "synonyms": list(synonyms),
        "description": description,
    }


# ------------------------------------------------------- upper-ontology pruning

# Upper-ontology namespaces whose classes ("entity", "material entity", …) are
# too generic to search on. Dropped from ancestor walks. Note: OLS reports these
# under the importing ontology (UBERON etc.), so they must be filtered by ID
# namespace, not by `ontology_name`.
_UPPER_ONTOLOGY_PREFIXES = frozenset({"BFO", "CARO", "COB", "OBI", "IAO"})

# Generic root terms that live in an otherwise-useful namespace (so they can't be
# dropped by prefix) — matched by full OBO id. UBERON:0000000 is UBERON's own root.
_GENERIC_TERM_IDS = frozenset({"UBERON:0000000"})


def _term_prefix(term: dict) -> str:
    """ID namespace of an OLS term (e.g. 'BFO' from 'BFO:0000001'), upper-cased."""
    obo_id = term.get("obo_id") or ""
    if ":" in obo_id:
        return obo_id.split(":", 1)[0].upper()
    tail = (term.get("iri") or "").rsplit("/", 1)[-1]
    return tail.split("_", 1)[0].upper() if "_" in tail else ""


def _is_upper_ontology(term: dict) -> bool:
    """True if an OLS term is too generic to search on (upper-ontology root)."""
    return (
        _term_prefix(term) in _UPPER_ONTOLOGY_PREFIXES
        or (term.get("obo_id") or "").upper() in _GENERIC_TERM_IDS
    )


# ------------------------------------------------------------- public handler API


def search_classes(
    term: str, ontology: str | None = None, *, rows: int = 10
) -> list[dict]:
    """searchClasses: resolve ``term`` to matching ontology classes (distilled)."""
    params: dict[str, Any] = {
        "q": term,
        "type": "class",
        "fieldList": _SEARCH_FIELDS,
        "rows": rows,
    }
    if ontology:
        params["ontology"] = ontology.lower()
    data = _ols_get("search", params)
    docs = ((data or {}).get("response") or {}).get("docs") or []
    return [_distill(doc) for doc in docs]


def top_class(term: str, ontology: str | None = None) -> dict | None:
    """The single best-matching class for ``term`` (distilled), or None."""
    docs = search_classes(term, ontology, rows=1)
    return docs[0] if docs else None


def _to_iri(term_id: str) -> str:
    """Turn an OBO curie (UBERON:0002107) into its PURL IRI; pass IRIs through.

    Covers the OBO Foundry PURL pattern (UBERON/CL/GO/MONDO/NCBITaxon …). For an
    ontology that doesn't use OBO PURLs (e.g. EFO), pass the full IRI instead.
    """
    if "://" in term_id:
        return term_id
    if ":" in term_id:
        prefix, local = term_id.split(":", 1)
        return f"http://purl.obolibrary.org/obo/{prefix}_{local}"
    return term_id


def _resolve_iri_ontology(
    term: dict | str, ontology: str | None
) -> tuple[str | None, str | None]:
    """Derive (iri, ontology) from either a distilled class dict or an id/IRI."""
    if isinstance(term, dict):
        return term.get("iri"), (ontology or term.get("ontology_name"))
    return _to_iri(term), (ontology.lower() if ontology else None)


def get_children(
    term: dict | str,
    ontology: str | None = None,
    *,
    relation: str = "children",
    size: int = 50,
    drop_upper: bool = False,
) -> list[dict]:
    """getChildren: list a class's child terms (distilled).

    ``term`` may be a distilled class dict (from :func:`search_classes`, whose
    ``iri``/``ontology_name`` are reused) or an OBO curie / IRI string plus an
    explicit ``ontology``. ``relation`` selects the OLS4 sub-resource — default
    ``children`` (directly-asserted ``is-a`` subtypes); ``hierarchicalChildren``
    also pulls part-of / develops-from; ``descendants`` is the full subtree;
    ``ancestors`` walks upward (pair with ``drop_upper`` to skip generic roots).
    """
    if relation not in RELATIONS:
        raise ValueError(f"relation must be one of {RELATIONS}, got {relation!r}")
    iri, onto = _resolve_iri_ontology(term, ontology)
    if not iri or not onto:
        return []
    # OLS requires the IRI double-URL-encoded in the path segment.
    encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
    data = _ols_get(f"ontologies/{onto}/terms/{encoded}/{relation}", {"size": size})
    terms = ((data or {}).get("_embedded") or {}).get("terms") or []
    out: list[dict] = []
    for child in terms:
        if drop_upper and _is_upper_ontology(child):
            continue
        out.append(_distill(child))
    return out


def related_labels(
    term: dict | str,
    relation: str,
    max_terms: int,
    *,
    drop_upper: bool = False,
) -> list[str]:
    """Labels of a class's related terms — thin wrapper over :func:`get_children`.

    Used by ``search_expanded.py`` to gather expansion terms; skips children with
    no label.
    """
    children = get_children(
        term, relation=relation, size=max_terms, drop_upper=drop_upper
    )
    return [child["label"] for child in children if child.get("label")]


# --------------------------------------------------------------------- CLI


def _print_terms(terms: list[dict], *, as_json: bool) -> None:
    """Print the distilled projection — the small output that keeps context lean."""
    if as_json:
        print(json.dumps(terms, indent=2))
        return
    if not terms:
        print("(no terms)")
        return
    for term in terms:
        row = f"{term['obo_id'] or '-'}\t{term['label'] or '-'}"
        if term["synonyms"]:
            row += f"\tsyn: {'; '.join(term['synonyms'])}"
        print(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ols",
        description="Query EBI OLS4, printing only distilled term rows "
        "(keeps the full OLS JSON out of the caller's context).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_term_args(p: argparse.ArgumentParser, default_size: int = 50) -> None:
        """Args shared by every relation subcommand (children/descendants/ancestors)."""
        p.add_argument("term_id", help="OBO curie (UBERON:0002107) or full IRI")
        p.add_argument(
            "--ontology", required=True, help="ontology of the term, e.g. uberon"
        )
        p.add_argument(
            "--size",
            type=int,
            default=default_size,
            help=f"max terms to return (default: {default_size})",
        )
        p.add_argument("--json", action="store_true", help="emit JSON, not rows")

    p_search = sub.add_parser(
        "search", help="searchClasses: resolve a term to ontology classes"
    )
    p_search.add_argument("query", help="free-text term, e.g. 'liver'")
    p_search.add_argument(
        "--ontology", help="restrict to an ontology, e.g. uberon, cl, efo, mondo"
    )
    p_search.add_argument(
        "--rows", type=int, default=10, help="max classes to return (default: 10)"
    )
    p_search.add_argument("--json", action="store_true", help="emit JSON, not rows")

    p_children = sub.add_parser(
        "children", help="getChildren: a class's direct children"
    )
    _add_term_args(p_children)
    p_children.add_argument(
        "--hierarchical",
        action="store_true",
        help="include part-of / develops-from children, not just is-a subtypes",
    )

    p_descendants = sub.add_parser(
        "descendants", help="getDescendants: a class's full subtype subtree"
    )
    _add_term_args(p_descendants)

    p_ancestors = sub.add_parser(
        "ancestors", help="getAncestors: a class's broader parent terms"
    )
    _add_term_args(p_ancestors)
    p_ancestors.add_argument(
        "--include-upper",
        action="store_true",
        help="keep generic upper-ontology roots (entity, material entity); "
        "dropped by default because they match everything",
    )

    args = parser.parse_args(argv)

    if args.command == "search":
        terms = search_classes(args.query, args.ontology, rows=args.rows)
    elif args.command == "children":
        relation = "hierarchicalChildren" if args.hierarchical else "children"
        terms = get_children(
            args.term_id, args.ontology, relation=relation, size=args.size
        )
    elif args.command == "descendants":
        terms = get_children(
            args.term_id, args.ontology, relation="descendants", size=args.size
        )
    else:  # ancestors
        terms = get_children(
            args.term_id,
            args.ontology,
            relation="ancestors",
            size=args.size,
            drop_upper=not args.include_upper,
        )

    _print_terms(terms, as_json=args.json)
    print(f"# {len(terms)} term(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
