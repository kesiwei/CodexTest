# oracleMcpTest.py
from mcp.server.fastmcp import FastMCP
import cx_Oracle
import argparse
from urllib.parse import urlparse

# 解析命令行参数
parser = argparse.ArgumentParser(description="Oracle MCP Server")
parser.add_argument("--dsn", required=True, help="Oracle connection string, e.g. oracle://user:pass@host:1521/service")
args = parser.parse_args()

# 解析 DSN URL
dsn_url = urlparse(args.dsn)

if dsn_url.scheme != "oracle":
    raise ValueError("DSN must start with oracle://")

user = dsn_url.username
password = dsn_url.password
host = dsn_url.hostname
port = dsn_url.port or 1521
service = dsn_url.path.lstrip("/")

# 创建 MCP 服务
mcp = FastMCP("OracleQuery")

@mcp.tool()
def query_oracle(sql: str) -> list[dict]:
    """
    执行一段 SQL 查询，并返回结果。
    示例: SELECT * FROM EMP_SCOTT_SAMPLE
    """
    dsn = cx_Oracle.makedsn(host, port, service_name=service)
    conn = cx_Oracle.connect(user=user, password=password, dsn=dsn)

    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        result = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return result
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    mcp.run(transport="stdio")
