# oracle_query_mcp_nopd.py
from mcp.server.fastmcp import FastMCP
import cx_Oracle

mcp = FastMCP("OracleQuery")


@mcp.tool()
def query_oracle(sql: str) -> list[dict]:
    """
    执行一段 SQL 查询，并返回结果。
    示例: SELECT * FROM EMP_SCOTT_SAMPLE
    """
    dsn = cx_Oracle.makedsn("192.168.56.130", 1521, service_name="bfcsdb_pdb")
    conn = cx_Oracle.connect(user="TEST_USER", password="123456", dsn=dsn)

    try:
        cursor = conn.cursor()
        cursor.execute(sql)

        # 获取列名
        columns = [desc[0] for desc in cursor.description]

        # 把每行转成 dict
        result = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return result
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
