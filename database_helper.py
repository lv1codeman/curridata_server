import pyodbc
from contextlib import contextmanager

# 自訂資料庫例外類別，用於更精確的錯誤處理
class DatabaseError(Exception):
    """資料庫操作時的一般錯誤。"""
    pass

class UniqueConstraintError(DatabaseError):
    """資料庫唯一約束條件衝突錯誤。"""
    pass

# 請將這裡的連接字串替換為您的實際資料庫連線資訊
# 例如: 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=your_server;DATABASE=your_db;UID=your_user;PWD=your_password'
# 注意: 在 Windows 上，驅動程式名稱可能不同
connection_string = 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-0O8RKB2;DATABASE=CURRIDATA;Trusted_Connection=yes;'

@contextmanager
def DatabaseCursor():
    """
    提供一個可管理的資料庫連線和游標。
    在 with 區塊結束時會自動提交或回滾。
    """
    conn = None
    cursor = None
    try:
        conn = pyodbc.connect(connection_string, autocommit=False)
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except pyodbc.Error as ex:
        if conn:
            conn.rollback()
        sqlstate = ex.args[0]
        if sqlstate == '23000':
            raise UniqueConstraintError(f"Unique constraint violation: {ex}")
        raise DatabaseError(f"Database operation failed: {ex}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def execute_query(sql: str, params=None):
    """
    執行 SQL 查詢或命令並回傳結果。
    
    參數:
    - sql (str): 要執行的 SQL 語句。
    - params (tuple, 可選): SQL 語句的參數。
    
    回傳:
    - 如果是 SELECT 查詢，則回傳結果清單（每行是一個字典）。
    - 如果是 INSERT/UPDATE/DELETE，則回傳受影響的行數。
    - 如果沒有結果，則回傳空列表。
    
    例外:
    - 如果發生資料庫錯誤，則引發 DatabaseError 或 UniqueConstraintError。
    """
    with DatabaseCursor() as cursor:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
            
        # 檢查是否為 SELECT 查詢
        if sql.strip().upper().startswith('SELECT') or sql.strip().upper().startswith('EXEC'):
            columns = [column[0] for column in cursor.description]
            result = []
            for row in cursor.fetchall():
                result.append(dict(zip(columns, row)))
            return result
        else:
            return cursor.rowcount
