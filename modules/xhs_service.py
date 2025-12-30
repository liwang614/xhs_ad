# xhs_client.py
# Modular client for xiaohongshu-mcp (MCP Streamable HTTP)
#
# Usage as script:
#   python xhs_client.py "美食"
#
# Usage as module:
#   from xhs_client import XhsService
#   client = XhsService()
#   print(client.search_feeds("美食"))

from __future__ import annotations

import json
from typing import Any, Dict, Optional, List

import httpx

Json = Dict[str, Any]


class McpError(RuntimeError):
    pass


class XhsService:
    """
    xiaohongshu-mcp client (Streamable HTTP).
    Handles required MCP session steps:
      1) initialize (read protocolVersion + Mcp-Session-Id header)
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
        h = headers if headers is not None else self._headers()
        retries = 3
        last_exception = None
        
        for attempt in range(retries):
            try:
                # Only print if we are retrying or if it's a long operation (optional, but good for debugging)
                if attempt > 0:
                    print(f"DEBUG: Request attempt {attempt + 1}/{retries}...")
                
                r = self._http.post(self.url, headers=h, json=payload)
                r.raise_for_status()
                if not r.text.strip():
                    return None
                return r.json()
            except httpx.TimeoutException as e:
                last_exception = e
                print(f"DEBUG: Request timed out (attempt {attempt + 1}/{retries}).")
                if attempt < retries - 1:
                    import time
                    print("DEBUG: Waiting 2 seconds before retrying...")
                    time.sleep(2)
                    continue
                # Don't raise here, let the loop finish to raise McpError
        
        if last_exception:
            raise McpError(f"Request timed out after {retries} attempts: {last_exception}") from last_exception
        return None

    def _ensure_session_ready(self) -> None:
        # 1) initialize (once)
        if not self._protocol:
            retries = 3
            last_exception = None
            init = None
            
            for attempt in range(retries):
                try:
                    r = self._http.post(
                        self.url,
                        headers={"Content-Type": "application/json"},
                        json={"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize", "params": {}},
                    )
                    r.raise_for_status()
                    init = r.json()
                    
                    if "result" not in init:
                        raise McpError(f"initialize failed: {init}")
                    
                    self._protocol = init["result"]["protocolVersion"]
                    self._session_id = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
                    last_exception = None
                    break
                except httpx.TimeoutException as e:
                    last_exception = e
                    if attempt < retries - 1:
                        import time
                        time.sleep(2)
                        continue
                    # Don't raise here, let the loop finish
            
            if last_exception:
                raise McpError(f"Initialization timed out after {retries} attempts: {last_exception}") from last_exception

        # 2) notifications/initialized (once)
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
            raise McpError("tools/call returned isError")
        return result

    def search_feeds(
        self,
        keyword: str,
        sort_by: Optional[str] = None,
        publish_time: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
    ) -> Json:
        args: Dict[str, Any] = {"keyword": keyword}
        if filters is None:
            payload_filters: Dict[str, str] = {}
            if sort_by:
                payload_filters["sort_by"] = sort_by
            if publish_time:
                payload_filters["publish_time"] = publish_time
            if payload_filters:
                args["filters"] = payload_filters
        else:
            if filters:
                args["filters"] = filters
        return self.call_tool("search_feeds", args)

    def get_feed_detail(self, feed_id: str, xsec_token: str, load_all_comments: bool = False) -> Json:
        return self.call_tool(
            "get_feed_detail",
            {
                "feed_id": feed_id,
                "xsec_token": xsec_token,
                "load_all_comments": load_all_comments,
            },
        )

    def post_comment(self, feed_id: str, xsec_token: str, content: str) -> Json:
        return self.call_tool(
            "post_comment_to_feed",
            {
                "feed_id": feed_id,
                "xsec_token": xsec_token,
                "content": content,
            },
        )

    def like_feed(self, feed_id: str, xsec_token: str, unlike: bool = False) -> Json:
        return self.call_tool(
            "like_feed",
            {
                "feed_id": feed_id,
                "xsec_token": xsec_token,
                "unlike": unlike,
            },
        )

    def check_auth(self) -> bool:
        result = self.call_tool("check_login_status", {})
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            logged_in = result.get("logged_in")
            if isinstance(logged_in, bool):
                return logged_in
            if logged_in is not None:
                return bool(logged_in)
            texts = extract_text(result)
            for text in texts:
                if "已登录" in text or "登录成功" in text:
                    return True
                if "未登录" in text or "登录失效" in text:
                    return False
        return False

    def search(self, keyword: str) -> Json:
        return self.search_feeds(keyword)

    # 未来扩展（你后面要做别的功能就按这个模式加）
    # def publish_content(self, title: str, content: str, images: List[str]) -> Json:
    #     return self.call_tool("publish_content", {"title": title, "content": content, "images": images})


def extract_text(resp: Json) -> List[str]:
    """从 MCP 返回里提取 text 内容，方便直接打印"""
    out: List[str] = []
    if isinstance(resp, dict) and "content" in resp:
        content = resp.get("content", [])
    else:
        content = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                out.append(item["text"])
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print('Usage: python xhs_client.py "关键词"')
        raise SystemExit(2)

    keyword = sys.argv[1]
    with XhsService() as client:
        resp = client.search(keyword)
        texts = extract_text(resp)
        if texts:
            print("\n".join(texts))
        else:
            print(json.dumps(resp, ensure_ascii=False, indent=2))


# Backwards compatibility for existing scripts.
XhsMcpClient = XhsService
