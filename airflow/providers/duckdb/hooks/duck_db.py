import duckdb
from airflow.providers.common.sql.hooks.sql import DbApiHook


class DuckdbHook(DbApiHook):
    """Interact with DuckDB."""

    onn_name_attr = "duckdb_conn_id"
    default_conn_name = "duckdb_default"
    conn_type = "duckdb"
    hook_name = "Duckdb"
    placeholder = "?"

    def get_conn(self):
        conn_id = getattr(self, self.conn_name_attr)
        airflow_conn = self.get_connection(conn_id)
        conn = duckdb.connect(database=airflow_conn.host, read_only=True)
        return conn

    def get_uri(self) -> str:
        """Override DbApiHook get_uri method for get_sqlalchemy_engine()"""
        conn_id = getattr(self, self.conn_name_attr)
        airflow_conn = self.get_connection(conn_id)
        return f"duckdb:///{airflow_conn.host}"
