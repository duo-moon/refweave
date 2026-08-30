# Changelog

All notable changes are recorded here. Format: [Keep a Changelog].
Versioning: SemVer starting at 0.1.0. See [CONCEPTS.md § Stability &
versioning](docs/CONCEPTS.md#stability--versioning) for what patch vs.
minor bumps guarantee, and the persisted-state migration story.

[Keep a Changelog]: https://keepachangelog.com/en/1.1.0/

## [Unreleased]

## [0.1.0] — 2026-09-06

Initial public release. See [CONCEPTS.md](docs/CONCEPTS.md) for the
layered overview + public API contract, and [SECURITY.md](SECURITY.md)
for the threat model.

### Highlights

- **Confluence Cloud v2 + DC v1** — end-to-end, run against real
  corpora (K8s docs, 400+ pages). Rate-limited async HTTP with retries,
  XHTML parser hardened against XXE, macro handlers for
  code / callout / expand / anchor / include, `(space, title)`
  resolver.
- **Jira Cloud v3 + DC v2** — issues + comments. ADF (Cloud) and wiki
  markup (DC) parsers, `issue_link` / `subtask` / `parent` link
  vocabulary, tenant-wide issue-key resolver.
- **Markdown files** — via a `RawFileProvider` (local FS or shallow
  git clone). Frontmatter (YAML/TOML/JSON), markdown-it-py tokenizer,
  path-based resolver with optional URL-rewrite hook.
- **Graph-informed chunker (`PolicyChunker`)** — configurable
  rule pipeline. Six built-in Rules: `HeadingRule`, `SizeLimitRule`,
  `MinSizeRule`, `AtomicBlockRule`, `LinkOverlapRule`,
  `ClusterBoundaryRule`. `NavigationClassifier` for whatsnext-style
  section tagging.
- **Persistent storage** — `FsStore` (canonical JSON/JSONL blobs) +
  `SqliteStore` (rebuildable index + graph). `MemoryStore` as an
  in-RAM alternative for tests, notebooks, small corpora.
- **Graph queries** — Leiden clustering (`recompute_clusters`),
  chunk-to-chunk materialization over `same_target` and
  `anchor_follow` channels, `cluster_peers` / `by_cluster` for
  graph-expanded retrieval.
- **Analysis toolkit (`refweave.analysis`)** — `corpus_report`,
  `cluster_summary`, `document_graph_mermaid`, `chunk_with_context`,
  `export_jsonl`, and `dump_analysis` for a batched artefact pack.
- **Incremental sync** — version-based skip detection, resurrection
  handling, tombstones with wiped links/chunks. `rechunk()` rebuilds
  chunk artifacts without re-fetching documents.

### Public API surface

Full package/name list in [CONCEPTS.md § Public API
contract](docs/CONCEPTS.md#public-api-contract). Contract shape: stable
path is the package import (`from refweave.plugins.chunker import
PolicyChunker`), never the deep file path. Anything not listed in
CONCEPTS.md is internal and may move without notice. Top-level
`refweave/__init__.py` exposes only `__version__`.

### Security

- Confluence XHTML parsing uses `lxml.etree` with
  `resolve_entities=False` + `no_network=True` — external entity
  expansion (XXE) and network-fetch DTDs are blocked.
- YAML frontmatter uses `yaml.safe_load` — no arbitrary object
  construction.
- SQLite queries are fully parameterized. Document ids in FS layout
  are sanitized against Windows-reserved characters and path
  traversal.
- Credentials are never persisted or logged. `.env` and
  `refweave-store/` are gitignored by convention.

See [SECURITY.md](SECURITY.md) for the full threat model.

### Known limitations

- No CLI, no service, no daemon — refweave is a library.
- One writer per store; concurrent `sync()` on the same store is not
  supported.
- HTTP client, API endpoint wrappers, and source facades are covered by
  integration scripts rather than unit tests. See
  [test-coverage.md](docs/test-coverage.md) for the full gap list.
- Skipped documents are not re-chunked when the resolver assigns new
  targets to them. Trigger `rechunk()` explicitly.
- Chunker rule / classifier interaction is caller-tunable — the
  library does not enforce rule ordering.

### Not included in 0.1

Deferred to 0.2 or later:
- PostgresStore, S3-backed FsStore.
- Embedding integration, semantic-similarity Rule.
- Git-watch mode (incremental repo sync, follow-on-push) beyond the
  one-shot `GitCloneProvider` that ships today.
- Managed CLI / service.
- Interactive web UI.
- Kuzu / Neo4j graph store.

[Unreleased]: https://github.com/duo-moon/refweave/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/duo-moon/refweave/releases/tag/v0.1.0
