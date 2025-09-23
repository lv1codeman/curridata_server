import pyodbc

def get_db_connection():
    """建立並回傳一個新的資料庫連線。"""
    # 這裡放您的資料庫連線字串
    conn_str = 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-0O8RKB2;DATABASE=CURRIDATA;Trusted_Connection=yes;'
    return pyodbc.connect(conn_str)

class DatabaseCursor:
    """一個用於管理資料庫連線和游標的上下文管理器。"""
    def __init__(self):
        self.conn = None
        self.cursor = None

    def __enter__(self):
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        if self.conn:
            self.cursor.close()
            # 只有在沒有錯誤發生時才提交變更
            if exc_type is None:
                self.conn.commit()
            self.conn.close()

def execute_query(query, params=None):
    """一個用於執行查詢的通用函式。"""
    try:
        with DatabaseCursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # 如果是 SELECT 或 EXEC 查詢，則回傳結果
            if query.strip().upper().startswith(("SELECT", "EXEC")):
                columns = [column[0] for column in cursor.description]
                result = [dict(zip(columns, row)) for row in cursor.fetchall()]
                return result
            # 如果是 INSERT/UPDATE/DELETE 查詢，則回傳受影響的行數
            else:
                return cursor.rowcount
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        # 這裡可以加入更詳細的錯誤處理
        print(f"資料庫錯誤: {sqlstate}")
        return None
