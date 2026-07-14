"""Read-only command-line interface for querying the Scientific Dataset Catalog.

Installed as the ``catalog`` console script. Every subcommand issues only GET
requests. Output is a human-readable table when stdout is a terminal and JSON
when piped; override with ``--output/-o``.

Configuration comes from the environment:
    CATALOG_API_URL    base URL of the catalog (e.g. https://catalog.example.com)
    CATALOG_API_TOKEN  API token (issue one at <catalog>/docs -> /token/issue)

Subcommands:
    search       full-text + faceted search over datasets
    facets       discover the catalog's actual filter vocabulary (value + count)
    get          fetch one full dataset record by UUID or coordinates
    list         exact-coordinate dataset listing
    lineage      walk provenance edges up/down from a dataset
    collections  browse collections and their entries

Exit codes:
    0  success            3  authentication error (401)
    1  other client error 4  not found (404)
    2  usage / config     5  server or connection error (5xx / network)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn

from catalog_client.client.catalog import CatalogClient
from catalog_client.exceptions import (
    AuthenticationError,
    CatalogConnectionError,
    CatalogError,
    CatalogServerError,
    NotFoundError,
)
from catalog_client.models.dataset import (
    DatasetModality,
    DatasetRef,
    DatasetSortOption,
)
from catalog_client.models.lineage import LineageType

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_SERVER = 5


def _usage_error(message: str) -> NoReturn:
    """Report a configuration/usage problem and exit with EXIT_USAGE."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(EXIT_USAGE)


def _client() -> CatalogClient:
    url = os.environ.get("CATALOG_API_URL")
    token = os.environ.get("CATALOG_API_TOKEN")
    if not url or not token:
        _usage_error("set CATALOG_API_URL and CATALOG_API_TOKEN in the environment.")
    return CatalogClient(base_url=url, api_token=token)


def _dump(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _model(m: Any) -> dict:
    return m.model_dump(mode="json")


# ------------------------------------------------------------------ rendering


def _truncate(value: Any, width: int = 40) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    """Print ``rows`` as an aligned text table over ``(key, header)`` columns."""
    if not rows:
        print("(no results)")
        return
    keys = [key for key, _ in columns]
    headers = [header for _, header in columns]
    cells = [[_truncate(row.get(key)) for key in keys] for row in rows]
    widths = [len(header) for header in headers]
    for line in cells:
        widths = [max(width, len(cell)) for width, cell in zip(widths, line)]
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * width for width in widths]))
    for line in cells:
        print(fmt.format(*line))


def _print_kv(record: dict, fields: list[tuple[str, str]]) -> None:
    """Print selected ``(key, label)`` fields of a single record vertically."""
    label_width = max(len(label) for _, label in fields)
    for key, label in fields:
        print(f"{label.ljust(label_width)}  {_truncate(record.get(key), width=80)}")


_DATASET_COLUMNS = [
    ("id", "ID"),
    ("canonical_id", "CANONICAL_ID"),
    ("version", "VERSION"),
    ("modality", "MODALITY"),
    ("project", "PROJECT"),
    ("name", "NAME"),
]


def _dataset_summary(ds: Any) -> dict:
    """Compact view of a dataset record for lists and lineage nodes."""
    return {
        "id": ds.id,
        "canonical_id": ds.canonical_id,
        "version": ds.version,
        "name": ds.name,
        "project": ds.project,
        "modality": getattr(ds.modality, "value", ds.modality),
        "dataset_type": getattr(ds.dataset_type, "value", ds.dataset_type),
        "is_latest": getattr(ds, "is_latest", None),
        "last_modified_at": str(getattr(ds, "last_modified_at", None)),
    }


def _modality(value: str | None) -> DatasetModality | None:
    if value is None:
        return None
    try:
        return DatasetModality(value)
    except ValueError:
        members = ", ".join(m.value for m in DatasetModality)
        _usage_error(f"invalid --modality {value!r}; expected one of: {members}")


# ---------------------------------------------------------------------- search


def cmd_search(args: argparse.Namespace) -> None:
    # Relevance ordering only makes sense with a text query.
    sort = args.sort or ("relevance" if args.q else "last_modified")
    with _client() as client:
        response = client.datasets.search(
            q=args.q,
            modality=_modality(args.modality),
            project=args.project,
            is_latest=None if args.all_versions else True,
            access_scope=args.access_scope,
            organism=args.organism,
            tissue=args.tissue,
            sub_modality=args.sub_modality,
            assay=args.assay,
            disease=args.disease,
            development_stage=args.development_stage,
            facets=args.facets.split(",") if args.facets else None,
            sort=DatasetSortOption(sort),
            offset=args.offset,
            limit=args.limit,
        )
    if args.output == "json":
        _dump(_model(response))
        return
    _print_table([_model(hit) for hit in response.results], _DATASET_COLUMNS)


def cmd_facets(args: argparse.Namespace) -> None:
    with _client() as client:
        response = client.datasets.search(
            q=args.q,
            is_latest=None if args.all_versions else True,
            facets=args.fields.split(","),
            limit=1,
        )
    facets = _model(response)["facets"] or {}
    if args.output == "json":
        _dump({"total": response.total, "facets": facets})
        return
    for field, buckets in facets.items():
        print(f"\n{field}  ({response.total} datasets matched)")
        _print_table(buckets, [("value", "VALUE"), ("count", "COUNT")])


# ------------------------------------------------------------------ get / list


def cmd_get(args: argparse.Namespace) -> None:
    ref: str | DatasetRef
    if args.version or args.project:
        if not (args.version and args.project):
            _usage_error("coordinate lookup needs all of: REF --version --project")
        ref = DatasetRef(
            canonical_id=args.ref, version=args.version, project=args.project
        )
    else:
        ref = args.ref
    with _client() as client:
        dataset = client.datasets.get(
            ref,
            include_lineage=args.lineage,
            include_collections=args.collections,
        )
    record = _model(dataset)
    if args.output == "json":
        _dump(record)
        return
    _print_kv(
        record,
        [
            ("id", "ID"),
            ("canonical_id", "Canonical ID"),
            ("version", "Version"),
            ("project", "Project"),
            ("name", "Name"),
            ("modality", "Modality"),
            ("dataset_type", "Type"),
            ("is_latest", "Latest"),
            ("tombstoned", "Tombstoned"),
            ("description", "Description"),
            ("doi", "DOI"),
            ("created_at", "Created"),
            ("last_modified_at", "Modified"),
        ],
    )
    print(f"Locations   {len(record.get('locations') or [])}")
    print("(use -o json for the full record)")


def cmd_list(args: argparse.Namespace) -> None:
    with _client() as client:
        response = client.datasets.list(
            canonical_id=args.canonical_id,
            version=args.version,
            modality=_modality(args.modality),
            project=args.project,
            access_scope=args.access_scope,
            is_latest=None if args.all_versions else True,
            include_lineage=args.lineage,
            include_collections=args.collections,
            offset=args.offset,
            limit=args.limit,
        )
    summaries = [_dataset_summary(ds) for ds in response.results]
    if args.output == "json":
        out = _model(response)
        if not args.full:
            out["results"] = summaries
        _dump(out)
        return
    _print_table(summaries, _DATASET_COLUMNS)


# --------------------------------------------------------------------- lineage


def cmd_lineage(args: argparse.Namespace) -> None:
    lineage_type = LineageType(args.type) if args.type else None
    edges: dict[str, dict] = {}
    nodes: set[str] = {args.dataset_id}
    frontier: set[str] = {args.dataset_id}
    with _client() as client:
    # TODO: unoptimized graph traversal needs revisiting
        for _ in range(args.depth):
            discovered: set[str] = set()
            for ds_id in frontier:
                if args.direction in ("up", "both"):
                    page = client.lineages.list(
                        destination_dataset_id=ds_id,
                        lineage_type=lineage_type,
                        limit=100,
                    )
                    for edge in page.results:
                        edges[edge.id] = _model(edge)
                        discovered.add(edge.source_dataset_id)
                if args.direction in ("down", "both"):
                    page = client.lineages.list(
                        source_dataset_id=ds_id,
                        lineage_type=lineage_type,
                        limit=100,
                    )
                    for edge in page.results:
                        edges[edge.id] = _model(edge)
                        discovered.add(edge.destination_dataset_id)
            frontier = discovered - nodes
            nodes |= discovered
            if not frontier:
                break
        datasets = {}
        for ds_id in sorted(nodes):
            try:
                datasets[ds_id] = _dataset_summary(client.datasets.get(ds_id))
            except Exception as exc:  # keep tombstoned/unreadable nodes visible
                datasets[ds_id] = {"id": ds_id, "error": str(exc)}
    edge_list = list(edges.values())
    if args.output == "json":
        _dump(
            {
                "root": args.dataset_id,
                "direction": args.direction,
                "datasets": datasets,
                "edges": edge_list,
            }
        )
        return
    print(f"\ndatasets in lineage of {args.dataset_id} ({args.direction}):")
    _print_table(list(datasets.values()), _DATASET_COLUMNS)
    print("\nedges:")
    _print_table(
        edge_list,
        [
            ("source_dataset_id", "SOURCE"),
            ("lineage_type", "TYPE"),
            ("destination_dataset_id", "DESTINATION"),
        ],
    )


# ----------------------------------------------------------------- collections


_COLLECTION_COLUMNS = [
    ("id", "ID"),
    ("canonical_id", "CANONICAL_ID"),
    ("version", "VERSION"),
    ("collection_owner", "OWNER"),
    ("collection_type", "TYPE"),
    ("name", "NAME"),
]


def cmd_collections(args: argparse.Namespace) -> None:
    with _client() as client:
        if args.action == "list":
            collections = client.collections.list(
                canonical_id=args.canonical_id,
                version=args.version,
                offset=args.offset,
                limit=args.limit,
            )
            if args.output == "json":
                _dump(_model(collections))
            else:
                _print_table(
                    [_model(c) for c in collections.results], _COLLECTION_COLUMNS
                )
        elif args.action == "get":
            record = _model(client.collections.get(args.id))
            if args.output == "json":
                _dump(record)
            else:
                _print_kv(
                    record,
                    [
                        ("id", "ID"),
                        ("canonical_id", "Canonical ID"),
                        ("version", "Version"),
                        ("name", "Name"),
                        ("collection_owner", "Owner"),
                        ("collection_type", "Type"),
                        ("description", "Description"),
                        ("doi", "DOI"),
                    ],
                )
        elif args.action == "entries":
            entries = client.collections.list_entries(
                args.id, offset=args.offset, limit=args.limit
            )
            rows = [
                {
                    "entry_type": entry.entry_type,
                    "entry": _dataset_summary(entry.entry)
                    if entry.entry_type == "dataset"
                    else _model(entry.entry),
                }
                for entry in entries.results
            ]
            if args.output == "json":
                out = _model(entries)
                out["results"] = rows
                _dump(out)
            else:
                _print_table(
                    [
                        {
                            "entry_type": entry.entry_type,
                            "id": entry.entry.id,
                            "canonical_id": entry.entry.canonical_id,
                            "version": entry.entry.version,
                            "name": entry.entry.name,
                        }
                        for entry in entries.results
                    ],
                    [
                        ("entry_type", "KIND"),
                        ("id", "ID"),
                        ("canonical_id", "CANONICAL_ID"),
                        ("version", "VERSION"),
                        ("name", "NAME"),
                    ],
                )
        elif args.action == "parents":
            parents = client.collections.list_parents(
                args.id, offset=args.offset, limit=args.limit
            )
            if args.output == "json":
                _dump(_model(parents))
            else:
                _print_table([_model(c) for c in parents.results], _COLLECTION_COLUMNS)


# ------------------------------------------------------------------------ main


def _add_paging(parser: argparse.ArgumentParser, limit: int) -> None:
    parser.add_argument("--limit", type=int, default=limit)
    parser.add_argument("--offset", type=int, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog",
        description="Query the Scientific Dataset Catalog (read-only).",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-o",
        "--output",
        choices=["table", "json"],
        default=None,
        help="output format (default: table on a terminal, json when piped)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "search", parents=[common], help="full-text + faceted dataset search"
    )
    p.add_argument("--q", help="free-text query over name/metadata")
    p.add_argument("--organism")
    p.add_argument("--tissue")
    p.add_argument("--assay")
    p.add_argument("--disease")
    p.add_argument("--sub-modality")
    p.add_argument("--development-stage")
    p.add_argument("--project")
    p.add_argument("--access-scope")
    p.add_argument("--modality")
    p.add_argument("--facets", help="comma-separated facet fields to count")
    p.add_argument(
        "--sort",
        choices=[option.value for option in DatasetSortOption],
        help="default: relevance with --q, last_modified without",
    )
    p.add_argument("--all-versions", action="store_true")
    _add_paging(p, limit=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser(
        "facets",
        parents=[common],
        help="discover actual filter values in the catalog",
    )
    p.add_argument(
        "--fields",
        default="organism,tissue,assay,disease,project,modality,sub_modality",
        help="comma-separated facet fields",
    )
    p.add_argument("--q", help="restrict counts to text-query matches")
    p.add_argument("--all-versions", action="store_true")
    p.set_defaults(func=cmd_facets)

    p = sub.add_parser(
        "get", parents=[common], help="one full dataset by UUID or coordinates"
    )
    p.add_argument("ref", help="dataset UUID, or canonical_id when using coordinates")
    p.add_argument("--version", help="with --project: coordinate lookup")
    p.add_argument("--project")
    p.add_argument("--lineage", action="store_true", help="embed lineage edges")
    p.add_argument("--collections", action="store_true", help="embed collections")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser(
        "list", parents=[common], help="exact-coordinate dataset listing"
    )
    p.add_argument("--canonical-id")
    p.add_argument("--version")
    p.add_argument("--project")
    p.add_argument("--modality")
    p.add_argument("--access-scope")
    p.add_argument("--all-versions", action="store_true")
    p.add_argument("--lineage", action="store_true")
    p.add_argument("--collections", action="store_true")
    p.add_argument("--full", action="store_true", help="full records, not summaries")
    _add_paging(p, limit=100)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser(
        "lineage", parents=[common], help="walk provenance edges from a dataset"
    )
    p.add_argument("dataset_id", help="dataset UUID to start from")
    p.add_argument(
        "--direction",
        choices=["up", "down", "both"],
        default="both",
        help="up = toward sources/ancestors, down = toward derived datasets",
    )
    p.add_argument("--depth", type=int, default=3, help="max hops from the root")
    p.add_argument("--type", choices=[member.value for member in LineageType])
    p.set_defaults(func=cmd_lineage)

    p = sub.add_parser("collections", parents=[common], help="browse collections")
    p.add_argument("action", choices=["list", "get", "entries", "parents"])
    p.add_argument("id", nargs="?", help="collection UUID (get/entries/parents)")
    p.add_argument("--canonical-id")
    p.add_argument("--version")
    _add_paging(p, limit=100)
    p.set_defaults(func=cmd_collections)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "collections" and args.action != "list" and not args.id:
        parser.error(f"collections {args.action} requires a collection id")
    if args.output is None:
        args.output = "table" if sys.stdout.isatty() else "json"
    try:
        args.func(args)
    except AuthenticationError as exc:
        _fail(exc, EXIT_AUTH, "authentication failed — check CATALOG_API_TOKEN")
    except NotFoundError as exc:
        _fail(exc, EXIT_NOT_FOUND, "not found")
    except (CatalogServerError, CatalogConnectionError) as exc:
        _fail(exc, EXIT_SERVER, "catalog unreachable or server error")
    except CatalogError as exc:
        _fail(exc, EXIT_ERROR, "request failed")


def _fail(exc: CatalogError, code: int, hint: str) -> None:
    print(f"error: {hint}: {exc}", file=sys.stderr)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
