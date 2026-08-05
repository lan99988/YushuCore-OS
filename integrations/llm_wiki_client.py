from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from typing import Any, Callable


class LlmWikiApiError(RuntimeError):
    pass


class LlmWikiApiClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:19828",
        token: str | None = None,
        opener: Callable[..., Any] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = opener or urlopen
        self.timeout = timeout

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1{path if path.startswith('/') else '/' + path}"
        headers = {"Accept": "application/json"}
        if auth and self.token and self.token.strip():
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise LlmWikiApiError(
                "LLM Wiki API request failed; confirm the local app is running."
            ) from exc
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise LlmWikiApiError("LLM Wiki API returned non-JSON response") from exc
        if not isinstance(payload, dict):
            raise LlmWikiApiError("LLM Wiki API response must be an object")
        if payload.get("ok") is False:
            raise LlmWikiApiError(str(payload.get("error", "LLM Wiki request failed")))
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("/health", auth=False)

    def projects(self) -> dict[str, Any]:
        return self._request("/projects")

    def files(
        self,
        project_id: str = "current",
        *,
        root: str = "wiki",
        recursive: bool = True,
        max_files: int = 10000,
    ) -> dict[str, Any]:
        if root not in {"wiki", "sources", "all"}:
            raise ValueError("root must be wiki, sources, or all")
        if not 1 <= max_files <= 10000:
            raise ValueError("max_files must be between 1 and 10000")
        query = urlencode({"root": root, "recursive": str(recursive).lower(), "maxFiles": max_files})
        return self._request(f"/projects/{quote(project_id)}/files?{query}")

    def file_content(self, project_id: str, path: str) -> dict[str, Any]:
        normalized = path.replace("\\", "/").lstrip("/")
        if ".." in normalized or not (
            normalized.startswith("wiki/") or normalized.startswith("raw/sources/")
        ):
            raise ValueError("path must start with wiki/ or raw/sources/")
        query = urlencode({"path": normalized})
        return self._request(f"/projects/{quote(project_id)}/files/content?{query}")

    def reviews(
        self,
        project_id: str = "current",
        *,
        status: str = "unresolved",
        review_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        if status not in {"unresolved", "resolved", "all"}:
            raise ValueError("invalid review status")
        params: dict[str, Any] = {"status": status}
        if review_type:
            params["type"] = review_type
        if limit is not None:
            params["limit"] = limit
        suffix = f"?{urlencode(params)}" if params else ""
        return self._request(f"/projects/{quote(project_id)}/reviews{suffix}")

    def search(
        self,
        project_id: str,
        query: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query is required")
        options = dict(options or {})
        return self._request(
            f"/projects/{quote(project_id)}/search",
            method="POST",
            body={
                "query": query,
                "topK": options.get("topK"),
                "includeContent": options.get("includeContent", False),
            },
        )

    def graph(
        self,
        project_id: str = "current",
        *,
        q: str | None = None,
        node_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if q:
            params["q"] = q
        if node_type:
            params["nodeType"] = node_type
        if limit is not None:
            params["limit"] = limit
        suffix = f"?{urlencode(params)}" if params else ""
        return self._request(f"/projects/{quote(project_id)}/graph{suffix}")

    def rescan(self, project_id: str = "current") -> dict[str, Any]:
        return self._request(
            f"/projects/{quote(project_id)}/sources/rescan",
            method="POST",
        )
