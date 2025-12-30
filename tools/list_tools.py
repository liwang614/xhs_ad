import argparse
import json
import httpx

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18060/mcp")
    args = parser.parse_args()

    url = args.url.rstrip("/")

    with httpx.Client(timeout=60) as client:
        # 1) initialize: get protocolVersion + Mcp-Session-Id
        r = client.post(url, headers={"Content-Type": "application/json"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        })
        r.raise_for_status()
        init = r.json()
        if "result" not in init:
            print("initialize failed:\n", json.dumps(init, ensure_ascii=False, indent=2))
            return 1

        protocol = init["result"]["protocolVersion"]
        session_id = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")

        headers = {"Content-Type": "application/json", "MCP-Protocol-Version": protocol}
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        # 2) notifications/initialized
        r = client.post(url, headers=headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized"
        })
        r.raise_for_status()

        # 3) tools/list
        r = client.post(url, headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
        })
        r.raise_for_status()
        resp = r.json()

        if "error" in resp:
            print("tools/list error:\n", json.dumps(resp, ensure_ascii=False, indent=2))
            return 1
        if "result" not in resp:
            print("tools/list unexpected:\n", json.dumps(resp, ensure_ascii=False, indent=2))
            return 1

        tools = resp["result"].get("tools", [])

        print(f"toolsCount={len(tools)}\n")
        for i, t in enumerate(tools, 1):
            name = t.get("name", "")
            desc = t.get("description", "")
            schema = t.get("inputSchema")

            print(f"{i}. {name}")
            if desc:
                print(f"   desc: {desc}")
            if schema is not None:
                print("   inputSchema:", json.dumps(schema, ensure_ascii=False))
            print()

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
