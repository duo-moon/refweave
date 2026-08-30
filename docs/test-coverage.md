# Test coverage — status and known gaps

Snapshot as of 0.1.0 release audit. Refresh via
`poetry run pytest --cov=refweave --cov-report=term-missing`.

## Baseline

**82%** line coverage across 3.4K statements. **427** unit tests.

## Well-covered (>90%)

| Layer                 | Coverage | Notes                                     |
| --------------------- | -------- | ----------------------------------------- |
| `refweave.model`      | 100%     | Pure dataclasses / Pydantic models        |
| `refweave.ids`        | 100%     | Id helpers                                |
| `refweave.pipeline`   | 96–100%  | Orchestrator + Protocols                  |
| `refweave.plugins.chunker` | 100% | PolicyChunker + Rules + Classifiers       |
| `refweave.plugins.store.fs` | 97% | FsStore (blob layout, sharding, atomic writes) |
| `refweave.analysis`   | 95–100%  | Post-sync inspection tools                |
| Confluence `parser`   | 97%      | XHTML → StructuralElement (21 tests)      |
| Confluence `macros`   | 84%      | code/callout/anchor/expand/include        |
| Jira `parser_wiki`    | 99%      | Wiki-markup line-based state machine      |
| Jira `parser_adf`     | 89%      | ADF (Atlassian Document Format) → elements|
| Markdown `parser`     | 92%      | markdown-it token walker                  |
| Markdown `resolver`   | 95%      | Path normalization + url_rewriter         |
| Markdown `providers`  | 92%      | LocalDirectory + GitClone providers       |
| Markdown `frontmatter`| 95%      | YAML/TOML/JSON fence detection            |

## Known gaps

### Network-facing infra — no unit tests

These modules are exercised by ad-hoc integration runs against real
tenants (living locally in the gitignored `scripts/` directory), not
by unit tests. Adding mocked-HTTP unit tests is 0.2 work if it
becomes necessary — for now the shape is thin and the failure modes
surface fast against a real API.

| Module                                          | Coverage | Reason                       |
| ----------------------------------------------- | -------- | ---------------------------- |
| `refweave.plugins.source.base.http`             | 29%      | HttpClient rate-limit/retry loop — needs `respx` fixtures |
| `refweave.plugins.source.atlassian.pagination`  | 29%      | Cursor/next-link helpers     |
| `refweave.plugins.source.atlassian.auth`        | 65%      | Bearer/basic header construction |
| Confluence `cloud.py`, `dc.py`, `api.py`        | 0–33%    | API-endpoint wrappers        |
| Jira `cloud.py`, `dc.py`, `api.py`, `_mapping.py` | 0–33%  | API-endpoint wrappers + field extractors |

### Source facades — partial coverage (~50%)

`ConfluenceSource`, `JiraSource`, `MarkdownSource` — the class stitches
parser + link extractor + build together and drives `iter_pages` /
`iter_issues` / `provider.iter()`. Direct construction paths and
`__aenter__`/`__aexit__`/`aclose()` are unit-tested (`test_sync_e2e`),
but the deep integration path is only exercised via integration
scripts. Same rationale as above: thin wrappers, easier to verify
against a real API.

### Confluence link extractor & resolver — 30%

`Confluence links.py` (30%) — link-shape parsing for six kinds (page,
attachment, user, external, jira, include). Currently exercised only
via integration; unit tests are 0.2 work. Same shape as
`markdown.links.py` / `jira.links.py` — those are 91–100% covered, so
the pattern is well-tested somewhere.

`Confluence resolver.py` (28%) — identity-return `(space, title) →
doc_id` resolver. Shape matches `Jira resolver` and `Markdown
resolver`, both 100% covered.

### Store internals — 81–86%

`MemoryStore` (86%) and `SqliteStore` (81%) have uncovered branches in
their materialization helpers (`_compute_same_target`,
`_compute_anchor_follow`) — the paths are exercised via
`test_sqlite_materialize.py` / `test_memory.py` but a few edge cases
(empty clusters, single-chunk documents) aren't asserted directly.
Non-critical: the paths are covered end-to-end by `test_sync_e2e.py`.

## Not planned

- **100% coverage** — not a goal. Chasing coverage past ~90% on
  network-facing modules costs more than it's worth (mocks drift from
  reality; the paths are already validated against real tenants).
- **Integration test parity** — live-tenant runs live under gitignored
  `scripts/`, not `tests/`. They require real credentials and are
  meant for smoke-testing a specific release, not for CI.
- **Property-based tests** — considered for chunker rules but the
  rules are small and easy to hand-write cases for.

## How to expand

If a specific gap needs closing:

1. Add unit tests under `tests/unit/<same-shape-as-src>/test_<file>.py`.
2. Follow the existing style — no framework fixtures beyond
   `pytest-asyncio` and `tmp_path`.
3. Mock network only via `respx` (already in dev deps) — no ad-hoc
   monkey-patching of `httpx`.
4. Re-run `poetry run pytest --cov=refweave` to confirm improvement.
