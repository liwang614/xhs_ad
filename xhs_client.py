from modules.xhs_service import McpError, XhsMcpClient, XhsService, extract_text

__all__ = ["McpError", "XhsMcpClient", "XhsService", "extract_text"]

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print('Usage: python xhs_client.py "keyword"')
        raise SystemExit(2)

    keyword = sys.argv[1]
    with XhsService() as client:
        resp = client.search(keyword)
        texts = extract_text(resp)
        if texts:
            print("\n".join(texts))
        else:
            print(json.dumps(resp, ensure_ascii=False, indent=2))
