from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

Json = Dict[str, Any]


class McpError(RuntimeError):
    pass


class XhsService:
    """
    xiaohongshu-mcp client (Streamable HTTP).
    Session flow:
      1) initialize
      2) notifications/initialized
      3) tools/call
    """

    def __init__(self, url: str = "http://127.0.0.1:18060/mcp", timeout: float = 300.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(timeout=timeout)
        self._id = 0

        self._protocol: Optional[str] = None
        self._session_id: Optional[str] = None
        self._initialized_notified: bool = False

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "XhsService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._protocol:
            headers["MCP-Protocol-Version"] = self._protocol
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: Json, *, headers: Optional[Dict[str, str]] = None) -> Optional[Json]:
        resp = self._http.post(self.url, headers=headers if headers is not None else self._headers(), json=payload)
        resp.raise_for_status()
        if not resp.text.strip():
            return None
        return resp.json()

    def _ensure_session_ready(self) -> None:
        if not self._protocol:
            init_resp = self._http.post(
                self.url,
                headers={"Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize", "params": {}},
            )
            init_resp.raise_for_status()
            init_json = init_resp.json()
            if "result" not in init_json:
                raise McpError(f"initialize failed: {init_json}")

            protocol = init_json["result"].get("protocolVersion")
            if not protocol:
                raise McpError(f"initialize missing protocolVersion: {init_json}")

            self._protocol = str(protocol)
            self._session_id = init_resp.headers.get("Mcp-Session-Id") or init_resp.headers.get("mcp-session-id")

        if not self._initialized_notified:
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=self._headers(),
            )
            self._initialized_notified = True

    def call_tool(self, name: str, arguments: Optional[Json] = None) -> Json:
        self._ensure_session_ready()
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            },
            headers=self._headers(),
        )
        if resp is None:
            raise McpError(f"tools/call empty response: {name}")
        if "error" in resp:
            raise McpError(f"tools/call error: {resp['error']}")
        if "result" not in resp:
            raise McpError(f"tools/call missing result: {resp}")

        result = resp["result"]
        if isinstance(result, dict) and result.get("isError") is True:
            texts = extract_text(result)
            if texts:
                raise McpError("; ".join(texts))
            raise McpError("tools/call returned isError=true")
        return result

    def reply_comment_in_feed(
        self,
        *,
        comment_id: str,
        feed_id: str,
        xsec_token: str,
        content: str,
        tool_name: str = "reply_comment_in_feed",
    ) -> Json:
        return self.call_tool(
            tool_name,
            {
                "comment_id": comment_id,
                "feed_id": feed_id,
                "xsec_token": xsec_token,
                "content": content,
            },
        )

    def like_feed(
        self,
        *,
        feed_id: str,
        xsec_token: str,
        tool_name: str = "like_feed",
    ) -> Json:
        return self.call_tool(
            tool_name,
            {
                "feed_id": feed_id,
                "xsec_token": xsec_token,
            },
        )


def extract_text(resp: Json) -> List[str]:
    out: List[str] = []
    content = resp.get("content") if isinstance(resp, dict) else None
    if not isinstance(content, list):
        return out
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            out.append(item["text"])
    return out


# Backwards compatibility alias.
XhsMcpClient = XhsService
