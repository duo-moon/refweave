# refweave

Python library that pulls documents from wiki-like sources, builds a
`Document ↔ Section ↔ Link` graph, and produces **graph-informed
chunks** for downstream RAG or corpus analysis.

Refweave prepares data. Retrieval, embeddings, ranking, and prompting
belong to whatever downstream system consumes the chunks.

**Status:** 0.1.0. Three source plugins ship end-to-end:
Confluence (Cloud v2 + DC v1), Jira (Cloud v3 + DC v2), and Markdown
files (via local FS or shallow git clone). No CLI, no service, no
daemon — this is a library; `sync()` is the public API.

## What it does

- Pulls content from Confluence, Jira, or Markdown corpora with
  rate-limited, retrying, async HTTP (or filesystem / git for
  Markdown).
- Parses each source's native format (XHTML for Confluence, ADF / wiki
  for Jira, CommonMark + GFM for Markdown) into typed structural
  elements — headings, paragraphs, code, callouts, macros, anchors.
- Extracts links per section — inline, macros, includes, issue
  references — and resolves them to stable `document_id`s. Dead links
  are marked, not silently dropped.
- Chunks each document via a configurable rule pipeline that reads
  heading structure, size limits, link overlap, and Leiden cluster
  boundaries.
- Persists everything on disk: JSON/JSONL blobs (source of truth) +
  SQLite index (rebuildable, used for graph queries). An in-memory
  store ships for tests and notebooks.
- Exposes graph queries: per-cluster chunk retrieval, cluster peers,
  chunk-to-chunk edges over `same_target` and `anchor_follow` channels.

Incremental by design: unchanged documents are skipped on re-sync; only
touched documents get re-chunked; deletions produce tombstones.

## Install

```bash
pip install refweave
```

## Quick start

Pull a public docs repo, chunk it with a graph-informed policy, and
dump a full analysis pack (corpus report, per-cluster summaries,
Mermaid document graph, JSONL export) to `./tmp/quickstart-dump/`. No
credentials, no persistent state — everything runs in memory and takes
under 5 seconds after `pip install`.

Requires `git` on PATH.

```python
import asyncio
from pathlib import Path

from refweave.analysis import dump_analysis
from refweave.pipeline import Persistence, recompute_clusters, sync
from refweave.plugins.chunker import HeadingRule, Policy, PolicyChunker, SizeLimitRule
from refweave.plugins.source.markdown import (
    GitCloneProvider,
    MarkdownFileResolver,
    MarkdownSource,
)
from refweave.plugins.store import MemoryStore


async def main() -> None:
    store = MemoryStore()
    await store.init()
    persistence = Persistence(
        documents=store.documents,
        links=store.links,
        chunks=store.chunks,
        data=store.data,
        graph=store.graph,
        query=store.query(),
    )

    chunker = PolicyChunker(
        policy=Policy([HeadingRule(), SizeLimitRule(max_chars=4000)]),
    )
    source = MarkdownSource(
        source_id="fastapi",
        provider=GitCloneProvider(
            url="https://github.com/fastapi/fastapi.git",
            ref="master",
            subdir="docs/en/docs",
        ),
    )

    async with source:
        await sync(source, chunker, persistence, MarkdownFileResolver())
    await recompute_clusters("fastapi", persistence)

    result = await dump_analysis(persistence, "fastapi", Path("./tmp/quickstart-dump"))
    print(f"analysis saved to {result.out_dir}")


asyncio.run(main())
```

After the run, browse `./tmp/quickstart-dump/`:

    README.md            index page linking to the rest
    report.md            corpus summary (docs, chunks, clusters, link stats)
    graph.mmd            Mermaid document graph — coloured by cluster
    chunks.jsonl         every chunk + cluster/backlink info, one per line
    clusters/            one Markdown file per top cluster (auto-label,
                         sample chunks, related clusters)

Paste `graph.mmd` into any Mermaid renderer (GitHub, GitLab, most
notebooks, [mermaid.live](https://mermaid.live)) to see the corpus
topology. Pass `graph_max_nodes=None` to `dump_analysis` if you want
the entire graph instead of the default top-50 nodes.

Swap `MemoryStore` for `FsStore + SqliteStore` when you want the
corpus on disk and reusable across processes. Swap `GitCloneProvider`
for `LocalDirectoryProvider(root="./docs")` if the docs are already
checked out. Swap the whole `MarkdownSource(...)` for
`ConfluenceSource(...)` / `JiraSource(...)` (see Use cases below) to
pull from Atlassian instead.

## Reference

- [`docs/CONCEPTS.md`](docs/CONCEPTS.md) — layers, model, sync phases,
  extension points, public API contract, FS layout.
- [`SECURITY.md`](SECURITY.md) — threat model, credential handling.
- [`CHANGELOG.md`](CHANGELOG.md) — release notes.

## Use cases

### 1. Building a graph-aware RAG corpus

**Problem.** Vanilla chunking splits pages into fixed-size windows and
throws away the link structure. On wiki-like corpora that structure
carries most of the semantic signal — cross-references group related
concepts far better than lexical similarity does.

**What refweave gives you.** Chunks whose boundaries respect the graph:
`LinkOverlapRule` merges consecutive sections that point to overlapping
targets; `ClusterBoundaryRule` splits when the outgoing-target clusters
diverge. Combined with heading structure and size limits, the resulting
chunks are semantically coherent and retrieval-ready.

```python
from refweave.plugins.chunker import (
    ClusterBoundaryRule,
    HeadingRule,
    LinkOverlapRule,
    MinSizeRule,
    Policy,
    PolicyChunker,
    SizeLimitRule,
)

chunker = PolicyChunker(
    policy=Policy([
        MinSizeRule(min_chars=500),
        HeadingRule(levels=[1, 2]),            # respect major boundaries
        LinkOverlapRule(threshold=0.3),        # merge sections that link to same places
        ClusterBoundaryRule(                   # split when target clusters diverge
            clusters=prior_clusters, threshold=0.7,
        ),
        SizeLimitRule(max_chars=4000),
    ]),
)
report = await sync(source, chunker, persistence, resolver)
```

### 2. Incremental sync — refresh a live corpus cheaply

**Problem.** A corpus with thousands of pages, most unchanged between
runs. Re-pulling everything wastes API budget and time; re-chunking
everything obliterates cached embeddings downstream.

**What refweave gives you.** Version-based skip detection at the
document level: pages whose `sync.version` matches the stored snapshot
are not re-fetched, not re-chunked, not touched. Deletions become
tombstones (`deleted_at` set, links/chunks wiped). Resurrection is
detected explicitly. Tuning the chunker with a different `max_chars`
does not require a re-sync — call `rechunk(source_id, chunker,
persistence)` and only the chunk artifacts get rebuilt.

```python
# First run — populates ./store/
await sync(source, chunker, persistence, resolver)

# Daily cron — only changed documents hit the source and get re-chunked
report = await sync(source, chunker, persistence, resolver)
print(f"changed: {report.created + report.updated}, skipped: {report.skipped}")

# Try a different chunker policy, keep the pulled docs / links
tighter = PolicyChunker(policy=Policy([SizeLimitRule(max_chars=2000)]))
await rechunk("acme", tighter, persistence)
```

### 3. Graph-expanded retrieval

**Problem.** Semantic-similarity top-K returns chunks that sound alike
but may miss the piece of context that actually answers the question —
the definition anchored at the top of the linked page, or the sibling
step in the same procedure.

**What refweave gives you.** After `sync()` populates chunk-to-chunk
edges and `recompute_clusters()` assigns each chunk to a Leiden cluster,
the graph is queryable: given any chunk you can pull siblings from the
same cluster, walk `anchor_follow` edges to chunks that point into a
specific anchor, or enumerate a whole cluster for coverage-first
prompting.

```python
await recompute_clusters("acme", persistence)

# During retrieval: seed from lexical / embedding search, then expand
seed = await persistence.query.get_chunk("acme", chunk_id)
if seed and seed.cluster_id is not None:
    peers = [
        p async for p in persistence.query.cluster_peers(
            "acme", chunk_id, limit=5,
        )
    ]
    # feed peers into your rerank / prompt-stuffing stage
```

### 4. Offline evaluation — reproducible chunker / retrieval experiments

**Problem.** Comparing chunker configurations or retrieval strategies
against a moving target (a live wiki, an evolving repo) makes results
non-reproducible. Every re-run pulls slightly different data.

**What refweave gives you.** Sync once, freeze the store. The FS layout
is the canonical dataset; the SQLite index is derivable. Point multiple
experiments at the same `./store/` directory, `rechunk()` with different
policies into separate output copies, compare metrics on identical
inputs. Version-stamping (`document.graph_version`) lets you tie
downstream artifacts to the corpus snapshot that produced them.

```python
# Freeze the corpus
await sync(source, base_chunker, persistence, resolver)

# Sweep chunker configs against the frozen store
for max_chars in (1000, 2000, 4000, 8000):
    chunker = PolicyChunker(policy=Policy([
        MinSizeRule(min_chars=max_chars // 8),
        SizeLimitRule(max_chars=max_chars),
    ]))
    await rechunk("acme", chunker, persistence)
    # measure retrieval quality on your eval set here
```

### 5. Docs-quality audit — dead links, orphans, dangling anchors

**Problem.** Wiki corpora rot. Pages get renamed, files get deleted,
anchors change. Neither Confluence's own search nor a plain `git grep`
surfaces these inconsistencies as first-class signal.

**What refweave gives you.** The resolver output is a link-quality
report: `resolved=True, target_document=None` marks a link whose target
is not present in the synced corpus (rename, cross-space reference,
deleted file). Combine with a reverse-index over `links` to find
orphan documents (no incoming links) and dangling anchors (link's
`target_anchor` with no matching `Section.metadata['anchor']`).

```python
await sync(source, chunker, persistence, resolver)

# Corpus-internal link kinds — filtering these out excludes intentional
# `external`/`user` links that also carry `resolved=True, target=None`.
INTERNAL = {
    "page", "include", "attachment",           # Confluence
    "issue_link", "subtask", "parent",         # Jira
    "internal",                                # Markdown
}

dead: list[str] = []
async for doc in persistence.documents.iter("acme"):
    async for link in persistence.links.get("acme", doc.id):
        if link.kind not in INTERNAL:
            continue
        if link.resolved and link.target_document is None:
            dead.append(f"{doc.title!r}: link seq={link.seq} kind={link.kind}")

for entry in dead[:20]:
    print(entry)
print(f"... {len(dead)} dead links total")
```

## What refweave is not

- Not a retrieval engine — no embeddings, no vector store, no reranker,
  no BM25. Bring your own.
- Not an LLM wrapper — no prompt templates, no completion helpers.
- Not a service — no daemon, no CLI, no HTTP API. Just functions.
- Not a config loader — hand-instantiate components in Python, pass
  them to `sync()`. Serialization is the caller's problem.
- Not a scheduler — `sync()` is a function. Run it from cron, Airflow,
  a Kubernetes CronJob, or a Python loop; refweave does not care.

## Contributing / dev

```bash
poetry install --with dev
poetry run pytest
poetry run ruff check src tests
poetry run mypy src tests
```

## License

MIT.
