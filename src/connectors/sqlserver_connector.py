"""
DataPilot — SQL Server / Azure SQL Connector
==============================================
Implementation of BaseConnector for Microsoft SQL Server and Azure SQL Database using pyodbc.
"""

import logging
import time
from typing import Dict, List, Optional
import pyodbc

from connectors.base import BaseConnector, ColumnInfo, TableInfo, QueryResult

logger = logging.getLogger("datapilot.connector.sqlserver")

class SQLServerConnector(BaseConnector):
    """Connector for SQL Server and Azure SQL Database."""
    
    def __init__(self, settings):
        super().__init__(settings)
        # pyodbc connection parameters
        self.server = getattr(settings, "db_host", "localhost")
        self.port = getattr(settings, "db_port", 1433)
        self.database = getattr(settings, "db_database", "")
        self.username = getattr(settings, "db_user", "")
        self.password = getattr(settings, "db_password", "")
        # Defaults to dbo schema if not specified
        self.schema = getattr(settings, "db_schema", "dbo")
        
    def connect(self):
        """Establish connection to SQL Server via pyodbc."""
        if self.is_connected():
            return

        try:
            # typical connection string for SQL Server / Azure SQL
            # Note: The driver name might vary. We'll use the recommended ODBC Driver 17 for SQL Server 
            # as a default, but ideally it should be configurable. We'll try a few common drivers.
            drivers = [x for x in pyodbc.drivers() if 'SQL Server' in x]
            if not drivers:
                raise Exception("No SQL Server ODBC drivers found on this system.")
            
            # Prefer the newest ODBC Driver for SQL Server (e.g. 18, 17, 13)
            driver = None
            for d in reversed(sorted(drivers)):
                if 'ODBC Driver' in d:
                    driver = d
                    break
            
            # fallback to whatever is available
            if not driver:
                driver = drivers[0]
                
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self.server},{self.port};"
                f"DATABASE={self.database};"
            )
            
            if self.username and self.password:
                conn_str += f"UID={self.username};PWD={self.password};"
            else:
                conn_str += "Trusted_Connection=yes;"
                
            self._connection = pyodbc.connect(conn_str, timeout=10)
            logger.info(f"Connected to SQL Server: {self.server} (Database: {self.database}) via {driver}")
        except Exception as e:
            logger.error(f"SQL Server connection failed: {e}")
            raise Exception(f"Failed to connect to SQL Server: {str(e)}")

    def disconnect(self):
        """Close the connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def is_connected(self) -> bool:
        """Check connection status."""
        if not self._connection:
            return False
        try:
            # Light ping
            cursor = self._connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except Exception:
            self._connection = None
            return False

    def discover_tables(self) -> List[TableInfo]:
        """Discover tables and views in the designated schema."""
        self.ensure_connected()
        tables = []
        
        sql = f"""
        SELECT 
            t.TABLE_NAME as table_name,
            t.TABLE_TYPE as table_type,
            p.rows as row_count
        FROM INFORMATION_SCHEMA.TABLES t
        LEFT JOIN sys.tables st ON t.TABLE_NAME = st.name AND st.schema_id = SCHEMA_ID(t.TABLE_SCHEMA)
        LEFT JOIN sys.partitions p ON st.object_id = p.object_id AND p.index_id IN (0,1)
        WHERE t.TABLE_SCHEMA = '{self.schema}'
        AND t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
        """
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql)
            
            for row in cursor.fetchall():
                t_name = row[0]
                t_type = row[1]
                t_rows = row[2] if row[2] is not None else 0 # views won't have rows here easily
                
                tables.append(
                    TableInfo(
                        name=t_name,
                        table_type=t_type,
                        schema_name=self.schema,
                        row_count=t_rows,
                    )
                )
        except Exception as e:
            logger.error(f"Failed to discover SQL Server tables: {e}")
        return tables

    def discover_columns(self, table_name: str) -> List[ColumnInfo]:
        """Discover columns for a specific table."""
        self.ensure_connected()
        columns = []
        
        sql = f"""
        SELECT 
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            COLUMN_DEFAULT,
            ORDINAL_POSITION
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{self.schema}' AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, table_name)
            
            for row in cursor.fetchall():
                col_name = row[0]
                data_type = row[1]
                is_nullable = (row[2].upper() == 'YES')
                col_default = row[3]
                ordinal = row[4]
                
                columns.append(
                    ColumnInfo(
                        name=col_name,
                        data_type=data_type,
                        nullable=is_nullable,
                        default=col_default,
                        ordinal=ordinal
                    )
                )
        except Exception as e:
            logger.error(f"Failed to discover SQL Server columns for {table_name}: {e}")
            
        return columns

    def discover_primary_keys(self, table_name: str) -> List[str]:
        """Discover primary keys for a table."""
        self.ensure_connected()
        pks = []
        
        sql = f"""
        SELECT c.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE c 
            ON tc.CONSTRAINT_NAME = c.CONSTRAINT_NAME 
            AND tc.TABLE_SCHEMA = c.TABLE_SCHEMA
        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' 
          AND tc.TABLE_SCHEMA = '{self.schema}'
          AND tc.TABLE_NAME = ?
        """
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, table_name)
            for row in cursor.fetchall():
                pks.append(row[0])
        except Exception:
            pass
        return pks

    def discover_foreign_keys(self, table_name: str) -> List[Dict[str, str]]:
        """Discover foreign keys for a table."""
        self.ensure_connected()
        fks = []
        
        sql = f"""
        SELECT 
            cu.COLUMN_NAME as fk_column,
            rcu.TABLE_NAME as ref_table,
            rcu.COLUMN_NAME as ref_column 
        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE cu 
            ON rc.CONSTRAINT_NAME = cu.CONSTRAINT_NAME
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE rcu 
            ON rc.UNIQUE_CONSTRAINT_NAME = rcu.CONSTRAINT_NAME
        WHERE cu.TABLE_SCHEMA = '{self.schema}' 
          AND cu.TABLE_NAME = ?
        """
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql, table_name)
            for row in cursor.fetchall():
                fk_col = row[0]
                ref_table = row[1]
                ref_col = row[2]
                fks.append({"column": fk_col, "references": f"{ref_table}.{ref_col}"})
        except Exception:
            pass
        return fks

    def sample_column_values(self, table_name: str, column_name: str, n: int = 5) -> List[str]:
        """Get N distinct sample values for a column, optimized for T-SQL."""
        self.ensure_connected()
        
        # In SQL Server, TOP N is used instead of LIMIT
        sql = f"""
        SELECT TOP {n} [{column_name}] AS val 
        FROM [{self.schema}].[{table_name}] 
        WHERE [{column_name}] IS NOT NULL 
        GROUP BY [{column_name}]
        """
        
        try:
            cursor = self._connection.cursor()
            cursor.execute(sql)
            
            samples = []
            for row in cursor.fetchall():
                val = row[0]
                samples.append(str(val) if val is not None else "")
            return samples
        except Exception:
            return []

    def execute_query(self, sql: str) -> QueryResult:
        """Execute a T-SQL query and return results."""
        self.ensure_connected()
        
        start_time = time.time()
        max_rows = getattr(self.settings, "max_result_rows", 10000)
        
        try:
            cursor = self._connection.cursor()
            # Execute with a basic timeout configured via an executing property on the connection normally
            # Pyodbc doesn't natively support statement timeouts across all drivers uniformly, 
            # but we can try to set it.
            cursor.execute(sql)
            
            # Fetch columns directly from description
            columns = [column[0] for column in cursor.description] if cursor.description else []
            
            # Fetch data with limits
            raw_rows = cursor.fetchmany(max_rows + 1)
            
            truncated = len(raw_rows) > max_rows
            if truncated:
                raw_rows = raw_rows[:max_rows]
                
            rows = []
            for raw_row in raw_rows:
                # Convert pyodbc Row to dict
                rows.append(dict(zip(columns, raw_row)))
                
            exec_time = (time.time() - start_time) * 1000
            
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=exec_time,
                truncated=truncated,
                query=sql,
                error=None
            )
            
        except Exception as e:
            exec_time = (time.time() - start_time) * 1000
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=exec_time,
                truncated=False,
                query=sql,
                error=str(e)
            )

    def get_dialect(self) -> str:
        return "sqlserver"

    def get_dialect_hints(self) -> str:
        return """
[DIALECT: T-SQL / Microsoft SQL Server]
- Use '[' and ']' for quoting identifiers, e.g. [Column Name]
- DO NOT use the "LIMIT" keyword. Use "TOP N" in your SELECT (e.g., SELECT TOP 100 col1 FROM table) 
- Use ISNULL() instead of COALESCE() for null handling.
- Use GETDATE() instead of NOW() for the current timestamp.
- For date parts logic, use DATEPART() or DATEDIFF().
- String concatenation uses the '+' operator, not '||'.
- Do NOT end the query with a semicolon.
"""
