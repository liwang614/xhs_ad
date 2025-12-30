import json
import httpx

URL = "http://127.0.0.1:18060/mcp"

def die(label, resp):
    print(f"\n[{label}]")
    print(json.dumps(resp, ensure_ascii=False, indent=2))
    raise SystemExit(1)

with httpx.Client(timeout=60) as client:
    # 1) initialize（拿 protocolVersion + Mcp-Session-Id）
    r = client.post(URL, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    })
    r.raise_for_status()
    init = r.json()

    if "result" not in init:
        die("initialize (no result)", init)

    protocol = init["result"].get("protocolVersion")
    if not protocol:
        die("initialize (missing protocolVersion)", init)

    # Streamable HTTP: session id comes from response header
    session_id = r.headers.get("Mcp-Session-Id")  # header lookup is case-insensitive
    # 兼容一些实现/代理可能用小写
    if not session_id:
        session_id = r.headers.get("mcp-session-id")

    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    print(f"protocolVersion={protocol}")
    print(f"sessionId={session_id}")

    # 2) notifications/initialized（必须在 tools/* 前发送）
    r = client.post(URL, headers=headers, json={
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    })
    r.raise_for_status()
    # 通知通常没有 JSON body，忽略即可

    # 3) tools/call -> check_login_status（无参数）
    r = client.post(URL, headers=headers, json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "check_login_status",
            "arguments": {}
        }
    })
    r.raise_for_status()
    resp = r.json()

    # 成功/失败都直接打印（不再 KeyError）
    print(json.dumps(resp, ensure_ascii=False, indent=2))
