# Record field values

## Computed fields

- **Size.** `size_bytes` is the asset's total bytes: the file size, or the sum over every file in a
  folder. Take it from storage metadata (`ChecksumResult.total_size`), not by reading the bytes.
  Unknown is unset, never `0`.
- **Checksums.** Prefer the client: `catalog checksum <path|s3://...>` from a shell, or
  `catalog_client.utils.checksum.compute_checksum(path, algorithm=...)` in code. Both stream in
  chunks and never load a file whole. Record the algorithm with the digest (`result.content_digest`,
  `result.algorithm.value`). Algorithm: `blake3` when the `checksum` extra is installed (fastest for
  very large files, and the default then), else `blake2b` (stdlib); on S3, `crc64nvme`/`crc32` let
  you reuse what S3 already stores instead of downloading.
- **Reusing storage checksums.** Check how a stored value was made before reusing it. A multipart S3
  ETag (`"…-N"`) is not an MD5 and not comparable across uploads; S3 composite (multipart) checksums
  depend on part size. The client's S3 path reuses only full-object checksums and ignores the rest.
- **File counts.** `file_count` for folders: count while walking (`os.walk`), not by listing into memory.

## Judgment fields

**Never invent a value.** Empty is honest; a fabricated value is a data-quality bug. If the source
lacks something optional (checksum, owner), leave it unset.

**Governance: ask a human; default to asking.** Allowed values are in the client's models (`registration-script`, Fields); meanings in the docs.

1. Does the user know the consent terms, data-use agreement, or source license for this data?
   No → stop and ask who does (the data owner or steward). Do not register.
2. Is the data derived from human participants (donor tissue, clinical samples, genotypes,
   identifiable images)? Yes → `is_pii`/`is_phi` come from the consent and the steward, in writing
   from the user. No (commercial cell lines, model organisms, synthetic data) → still have the user
   confirm both flags; never set them for the user.
3. `license` only as the user states it. `data_steward` is a named person or team the user gives.
4. Record each answer in `mapping.json`. Values that are unknown stay `null` so the record fails
   validation instead of shipping a guess.

**Data quality.** Each entry in `checks_passed` / `checks_failed` / `checks_skipped` needs evidence
the user can point to (a QC report, a metrics file, a pipeline step). Put the evidence files in
`report_assets` / `metrics_assets`. No evidence, no entry.

**Ontology terms.** An `ontology_id` is set only when an ontology lookup returns a term whose label
or synonym matches the source label exactly (case-insensitive), e.g. via the EBI OLS4 search API
(`https://www.ebi.ac.uk/ols4/api/search?q=<label>&ontology=<ncbitaxon|uberon|efo|cl|...>`). On no
confident match, or a failed lookup (retry a 429/5xx/timeout once), keep the label, leave
`ontology_id` unset, and list the gap for the user. A field may be filled from another column only
when that value formally determines it (a cell line's ontology ancestors pin its species); if it
could map to several values, leave it unset. Show the user the derivation rule and the rows it
leaves unset, and get approval before coding it.

**Fields with no named slot.** Keep them rather than dropping them: sample attributes as extra
keys on `with_sample(...)` (ontology concepts as `[OntologyEntry(...)]`, not bare strings),
measurements on `with_data_summary(...)`, experiment details on `with_experiment(...)`, and anything
else under the single `additional_metadata` key via `with_custom_metadata(additional_metadata={...})`;
governance is the exception: the `governance` block accepts extra keys, but access, consent or
compliance values with no named field (e.g. `consent`, `data_use_agreement`) go under
`additional_metadata`, not there. Use custom metadata only when no proper
field exists.
