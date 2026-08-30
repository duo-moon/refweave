# Concepts

One doc, top-down. Read it once to understand refweave; then reach for
the source when you need details.

## What refweave does

Pulls documents from wiki-like sources, builds a
`Document ↔ Section ↔ Link` graph, and produces graph-informed chunks
for downstream RAG or corpus analysis. It's a library — `sync()` is the
public entry point.

The pipeline is compositional: you construct a `Source`, a `Chunker`, a
`Persistence` bundle, and (optionally) a `Resolver`, then call
`sync()`. Retrieval, embeddings, prompting — not in scope.

## Layers

```
refweave.model             pure data types (Pydantic + frozen dataclasses)
refweave.pipeline          extension-point Protocols + sync/rechunk/recompute_clusters
refweave.plugins           implementations of Protocols
  .chunker                   PolicyChunker + Rules + Classifiers
  .store                     FsStore, SqliteStore, MemoryStore
  .source.base               HttpClient, AuthProvider, StructuralElement, id helpers
  .source.atlassian.*        Confluence, Jira
  .source.markdown           Markdown files (git or local)
  .keys / .kinds / .extras   metadata vocabulary + SectionKind + SourceExtra base
refweave.analysis          post-sync inspection (report, clusters, Mermaid, JSONL, dump)
refweave.ids               canonical ID formatting/parsing
refweave.graph             Leiden runner
```

Layering rules (enforced by `tests/unit/test_layering.py`):

- `pipeline/` doesn't import from `plugins/` — only Protocols.
- `plugins/` implements Protocols; peer subpackages don't reach into
  each other.
- `plugins/source/base/*` never imports a concrete product plugin.
- `plugins/store/*` reads metadata only via `refweave.plugins.keys`.

## Data model

Six domain types. All Pydantic `BaseModel` (or frozen dataclass), no
methods beyond serialization. See `src/refweave/model/` for exact fields.

| Type              | Purpose                                              |
| ----------------- | ---------------------------------------------------- |
| `Document`        | One page from a source. Ordered `Section`s + `SyncState`. |
| `Section`         | One top-level block (heading, paragraph, code, …).   |
| `Link`            | One outbound edge from a Section.                    |
| `Chunk`           | One retrieval-ready slice; spans one or more Sections. |
| `ChunkWithGraph`  | Chunk enriched with cluster id + anchor backlinks.   |
| `SyncState`       | `version`, `updated_at`, `deleted_at`.               |

**ID convention** (from `refweave.ids`). Colons are reserved:

- `doc:<source>:<external>` — Document
- `sec:<source>:<external>:<seq>` — Section
- `chunk:<source>:<external>:<seq>` — Chunk (`chk:` in practice)
- `lnk:<source>:<external>:<section_seq>:<link_seq>` — Link

Section/chunk ids are position-based: a moved section is a new section.
Chosen deliberately — content hash is more brittle than reorder detection.

**Link resolution states:**

- `resolved=False` — no Resolver has seen it.
- `resolved=True, target_document=<id>` — Resolver found the target.
- `resolved=True, target_document=None` — Resolver looked, target is
  outside the corpus. That's the "dead link" signature analysis tools
  read.

## Metadata vocabulary

Section/Chunk have `metadata: dict[str, Any]`. Two levels of vocabulary:

- **Cross-plugin** — `refweave.plugins.keys`:
  `HEADING_LEVEL_KEY`, `NAVIGATION_KEY`, `ANCHOR_KEY` on
  `Section.metadata`; `ANCHORS_KEY` on `Chunk.metadata`. Accessors
  (`heading_level`, `is_navigation`, `anchor`, `chunk_anchors`) enforce
  typing.
- **Plugin-specific** (Link routing) — each plugin has its own
  `keys.py` re-exported from the plugin package:
  Confluence `{SPACE_KEY, TITLE_KEY}`, Jira `{LINK_TYPE_KEY,
  TITLE_KEY, TARGET_KEY, DIRECTION_KEY}`, Markdown `{HREF_KEY,
  TARGET_PATH_KEY, TITLE_KEY}`. `TITLE_KEY = "title"` overlaps by name
  but Link never crosses plugin boundaries, so no collision.

Section content kind (`Section.kind: str`) draws from
`refweave.plugins.kinds.SectionKind` for cross-source structural
categories (`HEADING`, `PARAGRAPH`, `LIST`, `TABLE`, `CODE`, `QUOTE`,
`HR`, `UNKNOWN`) + plugin-specific `ElementKind` for extras
(`CALLOUT`/`EXPAND`/`ANCHOR`/`INCLUDE_PAGE` for Confluence,
`PANEL`/`COMMENT` for Jira, `HTML` for Markdown).

Document-level structured metadata (space, project, path, labels, …)
rides on a typed `SourceExtra` subclass per plugin (`ConfluenceExtra`,
`JiraExtra`, `JiraCommentExtra`, `MarkdownExtra`). Namespaced payload
under a `_<plugin>` key inside `Document.metadata` — access via
`Extra.read(doc.metadata)` / `Extra(...).write()`.

## The sync pipeline

`sync(source, chunker, persistence, resolver=None) -> SyncReport`.
Five phases:

1. **Pull** — iterate the source. For each `SyncedDocument`, skip if
   the stored `sync.version` matches (unchanged pages don't get
   re-fetched or re-chunked). Otherwise save doc + links, mark
   touched.
2. **Resolve** (optional) — the resolver walks the corpus once
   (`prepare`) to build a cross-doc index, then fills
   `target_document` per document (`resolve`). Identity-return
   contract: if nothing changed, return the input `links` object as-is
   so orchestrator can `is`-check and skip persistence.
3. **Chunk** — only touched docs are re-chunked. Skipped docs keep
   their previously stored chunks. `rechunk(source_id, chunker,
   persistence)` handles the case where you want to rebuild chunks
   without re-syncing.
4. **Tombstone** — docs present in the store but absent from this run
   get `deleted_at=now` and their links/chunks wiped.
5. **Materialize** — rebuild chunk-to-chunk graph relations
   (`same_target` + `anchor_follow` channels). Fresh sweep every time.

`recompute_clusters(source_id, persistence)` runs Leiden community
detection over `chunk_target` edges. Called independently — clustering
is optional.

## Storage

`FsStore` + `SqliteStore` is the shipping combo. `MemoryStore` is the
all-in-RAM alternative for tests, notebooks, small corpora.

- **`FsStore`** — canonical blobs on disk. Layout:
  `<root>/{documents,links,chunks}/<source_id>/<shard>/<safe_id>.<ext>`.
  Sharding = `sha256(document_id)[:2]`. Atomic writes via tmp +
  rename. Async I/O.
- **`SqliteStore`** — rebuildable index over the blobs. Tables:
  `document`, `chunk`, `chunk_anchor`, `chunk_target`, `cluster`,
  `chunk_relation`, `meta`. Materialization splits into
  `_compute_same_target` (in-memory Jaccard on target sets) and
  `_compute_anchor_follow` (single JOIN). Leiden runs in a
  `ProcessPoolExecutor` to keep the event loop responsive.

**`Persistence`** is a plain dataclass bundling the six sub-stores plus
a `GraphQuery`. It also owns three save-helpers that hide paired
writes:

- `save_document(doc)` = `documents.put + data.put`.
- `save_links(doc, links)` = `links.put`.
- `save_chunks(doc, chunks)` = `chunks.put + data.replace_chunks +
  graph.replace_chunk_targets`.

Impossible to forget a pair.

## The chunker

`PolicyChunker` is a buffer-driven engine. Every boundary is a call to
`Policy.decide(curr, buffer, ctx)`. Rules evaluate in order; first
non-`DEFER` wins; all-`DEFER` falls back to a default (`MERGE`).

Six built-in Rules:

- `HeadingRule(levels=None)` — SPLIT on a heading; restrict to `[1, 2]`
  for major-only boundaries.
- `SizeLimitRule(max_chars=4000)` — SPLIT when the buffer would
  exceed.
- `MinSizeRule(min_chars=500)` — MERGE while the buffer is under.
- `AtomicBlockRule` — MERGE a small buffer with an incoming
  code/table (protects orphaned headings before a fence).
- `LinkOverlapRule(threshold=0.3)` — MERGE when Jaccard(buffer targets,
  curr targets) ≥ threshold.
- `ClusterBoundaryRule(clusters, threshold=0.7)` — SPLIT when
  clusters diverge.

Plus `NavigationClassifier` — a post-emit callable that tags a chunk
whose first section is flagged `navigation=True`.

Rule order encodes the strategy. Consumer assembles `PolicyChunker`
by hand — there's no `make_chunker` factory, because the factory hid
which rules were active and why. The README Quick start block shows a
minimal Heading + SizeLimit combo; add `MinSizeRule`,
`LinkOverlapRule`, `ClusterBoundaryRule`, `AtomicBlockRule` as your
corpus and evaluation signals demand.

## Analysis

`refweave.analysis` is post-sync inspection over a `Persistence`
bundle:

- `corpus_report` — counts, link quality, top clusters.
- `cluster_summary` — sample chunks + related clusters (by
  document-level edge overlap).
- `document_graph_mermaid` — Mermaid `graph LR` string, cluster-tinted.
- `chunk_with_context` — expand a retrieved chunk with same-doc
  neighbours (RAG "context window" pattern).
- `export_jsonl` — every chunk + cluster/backlink info as JSONL.
- `dump_analysis` — batch: report + graph + chunks.jsonl +
  per-cluster Markdown, all in one call.

## Extension points

Everything is a Python `Protocol` in `refweave.pipeline`. Implement the
shape, hand the instance to `sync()`. No registry, no config file.

| Protocol            | Purpose                                         |
| ------------------- | ----------------------------------------------- |
| `Source`            | Pull raw content, emit `SyncedDocument`s.       |
| `Resolver`          | Fill `Link.target_document` cross-doc.          |
| `Chunker`           | `Document → Iterator[Chunk]`.                   |
| `Rule`              | One boundary decision inside `PolicyChunker`.   |
| `ChunkClassifier`   | Post-emit chunk-kind tagging.                   |
| `AuthProvider`      | HTTP auth injection for `HttpClient`.           |
| `RawFileProvider`   | File-tree backend for `MarkdownSource`.         |
| `DocumentStore`, `LinkStore`, `ChunkStore`, `DataIndex`, `GraphIndex`, `GraphQuery` | Custom store (Postgres, S3, …). |

Cross-plugin conventions the three built-in sources agree on:

- `def __init__(self, *, source_id: str, ..., link_extractor=None, ...)`
  — keyword-only, `source_id` first, `link_extractor` always an
  optional injection point.
- `async def aclose()` / `__aenter__` / `__aexit__` — own the HTTP
  client / clone cache, release on exit.
- `async def iter() -> AsyncIterator[SyncedDocument]` — the Protocol
  method name is fixed.
- Resolver `resolve` returns the input `links` object itself when
  nothing changed (identity check).

To write a new plugin, copy the shape of the closest built-in and
follow the tests in `tests/unit/plugins/source/<yours>/` as a
template. The Confluence plugin is the fullest reference.

## Public API contract

Stable for 0.1 → 0.2 minor:

- `refweave.pipeline` — `sync`, `rechunk`, `recompute_clusters`,
  `Persistence`, every extension-point Protocol, report dataclasses.
- `refweave.model` — the six domain types.
- `refweave.plugins.chunker` — `PolicyChunker`, `FixedWindowChunker`,
  `Policy`, `Rule`, `ChunkContext`, `Decision`, six built-in Rules,
  `NavigationClassifier`, `ChunkClassifier`.
- `refweave.plugins.store` — `FsStore`, `SqliteStore`, `MemoryStore`.
- `refweave.plugins.source.base` — `AuthProvider`, `HttpClient`,
  `StructuralElement`, `structural_element_to_section`, id/date
  helpers.
- `refweave.plugins.source.atlassian` — `ApiTokenAuth`, `PatAuth`,
  `NoAuth`, `paginate`, `next_link`.
- `refweave.plugins.source.atlassian.confluence` — `ConfluenceSource`,
  `ConfluencePageResolver`, `ConfluenceExtra`, `ConfluenceLinkKind`,
  `Tier`, `SPACE_KEY`, `TITLE_KEY`.
- `refweave.plugins.source.atlassian.jira` — `JiraSource`,
  `JiraIssueResolver`, `JiraExtra`, `JiraCommentExtra`, `JiraLinkKind`,
  `Tier`, four Link keys.
- `refweave.plugins.source.markdown` — `MarkdownSource`,
  `MarkdownFileResolver`, `MarkdownExtra`, `MarkdownLinkKind`,
  `RawFileProvider`, `LocalDirectoryProvider`, `GitCloneProvider`.
- `refweave.analysis` — the seven entry points listed above +
  return-type dataclasses.
- Top-level modules: `refweave.ids`, `refweave.plugins.keys`,
  `refweave.plugins.kinds`, `refweave.plugins.extras`.

**Contract shape:** the stable path is the package import
(`from refweave.plugins.chunker import PolicyChunker`). Deep-file
imports (`from refweave.plugins.chunker.chunkers import PolicyChunker`)
happen to work, but are not part of the contract — internal
reorganization can break them without notice.

Top-level `refweave/__init__.py` exposes only `__version__`. Assemble
your pipeline from the subpackages.

## Stability & versioning

SemVer. Refweave is 0.x — while the API is being pinned down, a minor
bump can ship intentional breaks. All breaks are called out in
[CHANGELOG.md](../CHANGELOG.md).

**What patch releases (0.1.0 → 0.1.1) guarantee:**

- No changes to any name listed under *Public API contract* above.
- No changes to model field names, types, or serialized JSON shapes.
- No changes to the on-disk `refweave-store/blob/` layout.
- No changes to `Section.metadata` / `Chunk.metadata` key vocabulary
  from `refweave.plugins.keys`.
- No changes to `<Plugin>LinkKind` string values.
- Bug fixes, docs, internal refactors, added `# noqa` comments.

**What minor releases (0.1 → 0.2) may break:**

- Any name in the public API — added, removed, renamed, resignatured.
- Model fields — added (with defaults, for forward-compat readers),
  removed, or retyped.
- SQLite schema in `refweave-store/index.sqlite` — tables added,
  dropped, indexes reshuffled. Rebuild strategy: delete
  `index.sqlite` and re-initialize `SqliteStore` — refweave rebuilds
  it from the blob layer on the next sync.
- FS blob layout under `refweave-store/blob/`. Migration path:
  re-sync from source. No in-place migration tool ships in 0.x.
- Plugin `keys.py` constant values (rare; would require re-sync).

**Persisted-state migration story:**

- `refweave-store/blob/` is the source of truth. A minor version bump
  may change the on-disk shape; the recommended migration path is a
  full re-sync from the source (`sync()` overwrites doc/link/chunk
  blobs).
- `index.sqlite` is derivable from `blob/`. On schema drift, the
  simplest recovery is `rm index.sqlite` + re-init `SqliteStore` + a
  no-op `sync()` — the store rehydrates from the blobs.
- If a minor bump ships an actual auto-migration, it will be called
  out in CHANGELOG.md with a fenced code block showing the recovery
  command.

**Internal — no stability guarantee at any release cadence:**

- Every symbol not listed under *Public API contract* above.
- SQLite table definitions, column names, index shapes.
- `_State`, `_FsJsonlStore`, `_SqliteGraphIndex`, and other private
  classes marked with the `_` prefix.
- `refweave.graph.run_leiden` — infrastructure, may be renamed or
  hidden.
- Test fixtures, benchmark scripts, integration scripts.

**Pre-1.0 clause:** the 0.x line intentionally leaves room to change
things that would be locked-in at 1.0. If you need long-term
stability, pin to `refweave==0.1.*` and read the changelog before
bumping the minor.

## What refweave is not

- Not a retrieval engine (no embeddings, no vector store, no reranker).
- Not an LLM wrapper (no prompt templates, no completion helpers).
- Not a service (no daemon, no CLI, no HTTP API).
- Not a config loader (hand-instantiate components in Python).
- Not a scheduler (`sync()` is a function).

## Known limitations

**Scale.** A synthetic Zipf-target benchmark on a Linux laptop
(single-threaded, warm cache) gives this baseline:

| Chunks | materialize | rebuild_clusters | edges emitted |
| ------ | ----------- | ---------------- | ------------- |
| 1 000  | ~1.2s       | ~0.1s            | ~45k          |
| 5 000  | ~9s         | ~0.5s            | ~296k         |
| 10 000 | ~30s (proj) | ~1s              | ~600k (proj)  |

`materialize_relations` is super-linear (Jaccard over candidate sets)
but not N² in practice. `save_document` + `save_chunks` add ~12ms per
doc — one round-trip per SQLite/FS store. On corpora >10k docs, that
loop dominates the sync.

**Concurrency.** One writer per store. `MemoryStore` and
`SqliteStore` assume a single `sync()` call at a time against a given
store; concurrent syncs may corrupt state.

**Rate-limit resilience.** If `sync()` is interrupted mid-run (Ctrl-C,
kill, network drop), the store is left in the state after the last
successfully persisted document. Re-running `sync()` is idempotent for
already-persisted docs (version-based skip), and picks up where it
left off for the rest. Materialization runs at the end — an
interrupted sync leaves stale `chunk_relation` rows for the touched
docs until the next successful `sync()` or `recompute_clusters()`.

**Encoding.** `MarkdownSource` expects UTF-8. Non-UTF-8 files
(Windows-1251, Latin-1, binary mis-tagged as `.md`) are logged as a
warning and skipped — the sync continues.

**Chunker rule ordering.** Rules run in the order you list them.
Getting boundary-cutting Rules (SPLIT-favoring) in the wrong position
can starve merge signals. The library does not enforce a "correct"
ordering; the built-in `PolicyChunker` docstring documents the
recommended shape.

**XML DoS.** `resolve_entities=False` + `no_network=True` on the
Confluence parser blocks XXE, but deeply nested XML can still slow
`lxml.etree` to a crawl. If you sync corpora from untrusted tenants,
wrap the parse step or run in a container with resource limits.
