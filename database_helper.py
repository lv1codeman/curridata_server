import pyodbc
from contextlib import contextmanager
from typing import Optional, Any, List, Dict

# 自訂資料庫例外類別，用於更精確的錯誤處理
class DatabaseError(Exception):
    """資料庫操作時的一般錯誤。"""
    pass

class UniqueConstraintError(DatabaseError):
    """資料庫唯一約束條件衝突錯誤。"""
    pass

# 請將這裡的連接字串替換為您的實際資料庫連線資訊
# 例如: 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=your_server;DATABASE=your_db;UID=your_user;PWD=your_password'
connection_string = 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-0O8RKB2;DATABASE=CURRIDB;Trusted_Connection=yes;'

@contextmanager
def DatabaseCursor():
    """
    提供一個可管理的資料庫連線和游標。
    在 with 區塊結束時會自動提交或回滾。
    """
    conn = None
    cursor = None
    try:
        # 使用 pyodbc.connect
        conn = pyodbc.connect(connection_string, autocommit=False)
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except pyodbc.Error as ex:
        if conn:
            conn.rollback()
        # pyodbc 的錯誤處理，23000 是常見的唯一約束錯誤 SQLSTATE
        sqlstate = ex.args[0]
        if '23000' in sqlstate:
             raise UniqueConstraintError(f"Unique constraint violation: {ex}")
        # 對於其他錯誤，引發一般的 DatabaseError
        raise DatabaseError(f"Database operation failed: {ex}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def execute_query(sql: str, params: Optional[tuple] = None, fetch_one: bool = False) -> Optional[Dict[str, Any] | List[Dict[str, Any]] | int]:
    """
    執行 SQL 查詢或命令並回傳結果。

    參數:
    - sql (str): 要執行的 SQL 語句。
    - params (tuple, 可選): SQL 語句的參數。
    - fetch_one (bool, 可選): 如果為 True，則只回傳第一筆結果（字典或 None）。

    回傳:
    - 如果是 SELECT 查詢且 fetch_one=True，回傳單一字典或 None。
    - 如果是 SELECT 查詢且 fetch_one=False，回傳結果清單（每行是一個字典）。
    - 如果是 INSERT/UPDATE/DELETE，則回傳受影響的行數 (int)。
    
    例外:
    - 如果發生資料庫錯誤，則引發 DatabaseError 或 UniqueConstraintError。
    """
    with DatabaseCursor() as cursor:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
            
        # 檢查是否為 SELECT 或 EXEC 查詢
        if sql.strip().upper().startswith('SELECT') or sql.strip().upper().startswith('EXEC'):
            # 獲取欄位名稱，用於將結果轉換為字典
            columns = [column[0] for column in cursor.description]
            
            if fetch_one:
                # 獲取單筆資料
                row = cursor.fetchone()
                # 如果有結果，將其與欄位名稱打包成字典；否則回傳 None
                if row:
                    return dict(zip(columns, row))
                return None
            else:
                # 獲取所有資料（原始行為）
                result = []
                for row in cursor.fetchall():
                    result.append(dict(zip(columns, row)))
                return result
        else:
            # 對於非查詢操作（INSERT/UPDATE/DELETE），回傳受影響的行數
            return cursor.rowcount
