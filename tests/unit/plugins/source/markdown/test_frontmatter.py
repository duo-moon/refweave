"""Tests for the frontmatter detector / parser."""

from __future__ import annotations

from refweave.plugins.source.markdown.frontmatter import parse_frontmatter


def test_no_frontmatter_returns_body_verbatim() -> None:
    meta, body, fmt = parse_frontmatter("Just body text.")
    assert meta == {}
    assert body == "Just body text."
    assert fmt == "none"


def test_yaml_frontmatter_parsed() -> None:
    src = "---\ntitle: Setup\ntags: [auth, ops]\n---\nBody.\n"
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {"title": "Setup", "tags": ["auth", "ops"]}
    assert body == "Body.\n"
    assert fmt == "yaml"


def test_toml_frontmatter_parsed() -> None:
    src = '+++\ntitle = "Setup"\ntags = ["auth"]\n+++\nBody.\n'
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {"title": "Setup", "tags": ["auth"]}
    assert body == "Body.\n"
    assert fmt == "toml"


def test_json_frontmatter_parsed() -> None:
    src = '{"title": "Setup", "tags": ["auth"]}\nBody.\n'
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {"title": "Setup", "tags": ["auth"]}
    assert body == "Body.\n"
    assert fmt == "json"


def test_malformed_yaml_falls_back_to_none() -> None:
    src = "---\ntitle: [unclosed\n---\nBody.\n"
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {}
    assert body == src
    assert fmt == "none"


def test_unclosed_yaml_fence_treated_as_body_only() -> None:
    src = "---\ntitle: Setup\nno closing fence here"
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {}
    assert body == src
    assert fmt == "none"


def test_empty_yaml_frontmatter_strips_fences_and_returns_empty_dict() -> None:
    src = "---\n# just a comment\n---\nBody.\n"
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {}
    assert body == "Body.\n"
    assert fmt == "yaml"


def test_yaml_frontmatter_that_is_not_a_mapping_is_rejected() -> None:
    # `--- - a --- - b ---` yields a list; we require a top-level mapping.
    src = "---\n- a\n- b\n---\nBody.\n"
    meta, body, fmt = parse_frontmatter(src)
    assert meta == {}
    assert body == src
    assert fmt == "none"


def test_json_without_body_still_parses() -> None:
    meta, body, fmt = parse_frontmatter('{"title": "X"}')
    assert meta == {"title": "X"}
    assert body == ""
    assert fmt == "json"


def test_json_non_object_ignored() -> None:
    # Array at the top is valid JSON but not a mapping — we reject.
    meta, body, fmt = parse_frontmatter("[1, 2, 3]\nBody.\n")
    assert meta == {}
    assert fmt == "none"


def test_only_three_dashes_line_is_not_yaml_frontmatter() -> None:
    # A single `---` followed by non-fence content shouldn't be treated as
    # frontmatter opener (it's a Markdown thematic break instead).
    src = "---\nSome text without closing fence\nmore text"
    _, body, fmt = parse_frontmatter(src)
    assert fmt == "none"
    assert body == src


def test_yaml_with_crlf_line_endings() -> None:
    src = "---\r\ntitle: X\r\n---\r\nBody.\r\n"
    meta, _body, fmt = parse_frontmatter(src)
    assert fmt == "yaml"
    assert meta == {"title": "X"}
