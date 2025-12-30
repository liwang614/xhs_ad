import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from xhs_client import XhsMcpClient

def my_search(keyword: str):
    with XhsMcpClient() as c:
        return c.search(keyword)

if __name__ == "__main__":
    print(my_search("旅行"))
