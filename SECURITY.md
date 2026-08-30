# Security policy

## Supported versions

`refweave` is 0.1 — pre-1.0. Only the latest minor is patched.

| Version | Patched |
| ------- | ------- |
| 0.1.x   | yes     |
| < 0.1   | no      |

## Reporting a vulnerability

Email the maintainer at the address listed in `pyproject.toml`
(`authors` field) or open a GitHub Security Advisory on the repository.
For sensitive reports, prefer email over a public issue.

Please include:
- Affected version (`refweave.__version__`).
- Steps to reproduce.
- Impact assessment (data exposure, RCE, DoS, etc.).

Aim for initial acknowledgement within 7 days.

## Threat model

`refweave` is a Python library that pulls documents from wiki-like
sources (Confluence, Jira, Markdown) and writes them to a local store.
It runs in the calling process with the calling user's credentials.

**In scope:**
- XXE / external-entity attacks via untrusted markup (XHTML from
  Confluence, ADF/wiki from Jira). Mitigation: `resolve_entities=False`
  + `no_network=True` on the `lxml.etree` parser.
- YAML deserialization attacks via Markdown frontmatter. Mitigation:
  `yaml.safe_load`.
- Path traversal via untrusted `document_id`, `path`, `href`.
  Mitigation: `_safe_filename` sanitization + relative-path
  normalization.
- SQL escape via attacker-controlled `source_id` / `document_id` /
  `chunk_id`. Mitigation: parametrized queries; ids never enter SQL as
  strings.
- Content-parsing DoS on hostile input (deeply nested XML, oversized
  documents, entity expansion).
- Secret leakage in logs, error messages, or persisted state.

**Out of scope:**
- Trust of the source itself: if Confluence is compromised, refweave
  will faithfully pull whatever it serves.
- Access control: refweave sees whatever the caller's API token /
  filesystem read permission sees; it does not enforce per-user ACLs.
- Sandboxing untrusted rules: `Rule`, `Chunker`, `Source`, `Resolver`
  are Python `Protocol`s — implementing them means running your code
  in-process. Only load plugins you trust.

## Credential handling

`refweave` **does not** store, cache, or log credentials. The library
accepts pre-materialized auth objects (`ApiTokenAuth`, `PatAuth`,
`NoAuth`) and passes them to `HttpClient`, which uses them per request.

Recommendations:
- Keep credentials in environment variables or a secret manager, not in
  code.
- `.env` and `.env.local` are gitignored — use them for local
  credentials without risking a commit.
- `scripts/` is gitignored — a good home for tenant-specific
  exploration entrypoints that shouldn't ship with the library.
- `refweave-store/`, `integration-state*/`, `*.sqlite` are gitignored —
  the persisted corpus can contain full document text and is not meant
  for version control.

## Known constraints

- **XHTML parsing** (Confluence storage format): uses `lxml.etree`
  with `resolve_entities=False` + `no_network=True` — external entity
  expansion (XXE) and network-fetch DTDs are blocked. Deeply nested
  trees are still theoretically DoS-able; refweave does not enforce a
  depth limit. If you sync corpora from untrusted tenants, wrap the
  parse step or run refweave in a resource-limited container.
- **Markdown parsing** (`markdown-it-py`): tokenizes as strings, does
  not execute embedded HTML. Frontmatter parsing (`pyyaml`) uses
  `safe_load` — no arbitrary object construction.
- **Git clone provider**: `GitCloneProvider` invokes `git clone` via
  `subprocess.run([...], shell=False)` — the URL is passed as an argv
  token, so shell-command injection is not possible. Still, pass only
  trusted URLs: a hostile URL can point at an internal Git endpoint
  (SSRF) or trigger credential prompts on SSH (`git@…` inherits the
  agent's identity).
- **SQLite index**: all values enter queries as bound parameters. One
  query in `_compute_same_target` uses an f-string to interpolate the
  placeholder *count* for a fixed-shape `NOT IN (?,?,...)` clause —
  the values themselves are still bound positionally. Ids
  (`source_id`, `document_id`, `chunk_id`, `link_id`, `cluster_id`)
  are treated as opaque strings/ints throughout.
- **FS layout**: `document_id` is sanitized via
  `_safe_filename` before being used as a filename — Windows-reserved
  characters, POSIX separators, and control bytes are replaced with
  `_`. Path traversal via crafted `document_id` (`../evil`) is
  blocked.
- **Multi-process safety**: refweave assumes one writer per store.
  Multiple concurrent `sync()` calls against the same
  `FsStore + SqliteStore` are not supported and may corrupt state.

## Non-goals

- Encryption of the store on disk. Rely on OS-level disk encryption
  (LUKS, FileVault, BitLocker) if you sync sensitive corpora.
- Audit log of every read/write. If your compliance model requires
  it, wrap the `DocumentStore` / `LinkStore` / `ChunkStore` Protocols
  and add logging in your implementation.
- Redaction of PII from ingested documents. Content is stored
  verbatim.
