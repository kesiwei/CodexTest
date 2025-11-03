# oracleOpOnceMcp.py
from mcp.server.fastmcp import FastMCP
import cx_Oracle
from urllib.parse import urlparse
import argparse
import datetime
import threading

# -----------------------
# 参数解析（支持 DSN URL）
# -----------------------
parser = argparse.ArgumentParser(description="Oracle 'one-op-then-decide' MCP")
parser.add_argument("--dsn", required=True, help="oracle://user:pass@host:1521/service")
args = parser.parse_args()

u = urlparse(args.dsn)
if u.scheme != "oracle":
    raise ValueError("DSN must start with oracle://")
USER = u.username
PWD = u.password
HOST = u.hostname
PORT = u.port or 1521
SERVICE = u.path.lstrip("/")

# -----------------------
# 连接与会话
# -----------------------
dsn = cx_Oracle.makedsn(HOST, PORT, service_name=SERVICE)
conn = cx_Oracle.connect(user=USER, password=PWD, dsn=dsn)
conn.autocommit = False
cur = conn.cursor()

# -----------------------
# MCP 实例 & 状态
# -----------------------
mcp = FastMCP("OracleOpOnce")
_state_lock = threading.Lock()
pending_op = {
    "open": False,           # 是否有“待确认”的操作
    "savepoint": None,       # 保存点名称（展示与记录）
    "sql": None,             # 本笔主 SQL
    "preview_sql": None,     # 本笔预览 SQL
    "time": None,            # 时间戳
}

def _now_tag():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def _ensure_no_pending():
    if pending_op["open"]:
        raise RuntimeError(
            "有尚未确认（提交/撤销）的操作。请先调用 commit_current 或 rollback_current 再进行下一笔。"
        )

# -----------------------
# 工具：状态查询
# -----------------------
@mcp.tool()
def op_status() -> dict:
    """查看当前是否有待确认操作。"""
    with _state_lock:
        return {
            "pending": pending_op["open"],
            "savepoint": pending_op["savepoint"],
            "sql": pending_op["sql"],
            "preview_sql": pending_op["preview_sql"],
            "time": pending_op["time"],
        }

# -----------------------
# 工具：按次执行（写操作）+ 预览
# -----------------------
@mcp.tool()
def execute_with_preview(sql: str, preview_sql: str) -> dict:
    """
    执行一笔写操作（DML/DDL/DCL），随后执行预览查询，返回预览结果。
    本工具会生成 SAVEPOINT 并标记本笔为 pending，必须 commit 或 rollback 后才能进行下一笔。
    参数：
      - sql: 需要执行的主 SQL（如 INSERT/UPDATE/DELETE/GRANT/ALTER 等）
      - preview_sql: 预览用 SELECT（例如“返回插入行及上下3行”的查询语句，调用方构造）
    返回：
      - savepoint, preview_rows（最多返回若干行，避免超大）
    """
    _ensure_no_pending()
    sp = f"sp_{_now_tag()}"

    try:
        # 记录保存点（用于可视化与回退锚点）
        cur.execute(f"SAVEPOINT {sp}")
        # 执行主 SQL
        cur.execute(sql)
        # 执行预览 SQL
        cur.execute(preview_sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(50)  # 保护：最多返回 50 行，避免刷爆聊天
        preview = [dict(zip(columns, r)) for r in rows]

        with _state_lock:
            pending_op["open"] = True
            pending_op["savepoint"] = sp
            pending_op["sql"] = sql
            pending_op["preview_sql"] = preview_sql
            pending_op["time"] = datetime.datetime.now().isoformat()

        return {
            "message": "执行成功，已返回预览结果。请决定提交或撤销。",
            "savepoint": sp,
            "preview_rows": preview,
        }

    except Exception as e:
        # 若主 SQL 或预览出错，整笔回滚干净
        conn.rollback()
        with _state_lock:
            pending_op["open"] = False
            pending_op["savepoint"] = None
            pending_op["sql"] = None
            pending_op["preview_sql"] = None
            pending_op["time"] = None
        raise

# -----------------------
# 工具：提交 / 撤销（必须二选一）
# -----------------------
@mcp.tool()
def commit_current() -> str:
    """提交当前待确认操作，并清空 pending 状态。"""
    with _state_lock:
        if not pending_op["open"]:
            return "当前没有待提交的操作。"
        conn.commit()
        pending_op["open"] = False
        sp = pending_op["savepoint"]
        pending_op["savepoint"] = None
        pending_op["sql"] = None
        pending_op["preview_sql"] = None
        pending_op["time"] = None
    return f"已提交。本笔保存点：{sp}"

@mcp.tool()
def rollback_current() -> str:
    """撤销当前待确认操作（整笔回滚），并清空 pending 状态。"""
    with _state_lock:
        if not pending_op["open"]:
            return "当前没有待撤销的操作。"
        # 一笔一清：直接回滚整个事务，最干净可靠
        conn.rollback()
        pending_op["open"] = False
        sp = pending_op["savepoint"]
        pending_op["savepoint"] = None
        pending_op["sql"] = None
        pending_op["preview_sql"] = None
        pending_op["time"] = None
    return f"已撤销。本笔保存点（记录用）：{sp}"

# -----------------------
# 工具：只读查询（不受 pending 限制）
# -----------------------
@mcp.tool()
def query_dql(sql: str) -> list[dict]:
    """纯查询（SELECT），不改变 pending 状态。"""
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(200)
    return [dict(zip(cols, r)) for r in rows]

# -----------------------
# 启动（stdio）
# -----------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
