"""Auth providers for Atlassian Cloud (API token) and DC/Server (PAT)."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


class ApiTokenAuth:
    """Atlassian API token via HTTP Basic scheme.

    Used by both Confluence Cloud and Jira Cloud with the same token.
    Docs: https://developer.atlassian.com/cloud/confluence/basic-auth-for-rest-apis/
    """

    def __init__(self, email: str, token: str) -> None:
        credentials = f"{email}:{token}".encode()
        self._header = f"Basic {base64.b64encode(credentials).decode('ascii')}"

    def apply(self, request: httpx.Request) -> None:
        request.headers["Authorization"] = self._header


class PatAuth:
    """Personal Access Token via Bearer scheme.

    Used by Confluence DC/Server and Jira DC/Server.
    Docs: https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html
    """

    def __init__(self, token: str) -> None:
        self._header = f"Bearer {token}"

    def apply(self, request: httpx.Request) -> None:
        request.headers["Authorization"] = self._header


class NoAuth:
    """No-auth provider — for reading public projects on anonymous-friendly
    Jira DC instances (e.g. `issues.apache.org/jira`).

    Cloud REST endpoints (`atlassian.net`, `jira.atlassian.com`) generally
    reject anonymous access even for otherwise-public data.
    """

    def apply(self, request: httpx.Request) -> None:
        del request
