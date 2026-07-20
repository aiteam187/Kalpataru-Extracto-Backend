import os
import struct
import datetime
from dotenv import load_dotenv
import pyodbc

load_dotenv()


def handle_datetimeoffset(dto_value):
    # pyodbc doesn't natively support SQL Server's datetimeoffset (SQL type -155);
    # decode the raw bytes it hands back instead of erroring out mid-dump.
    tup = struct.unpack("<6hI2h", dto_value)
    return datetime.datetime(
        tup[0], tup[1], tup[2], tup[3], tup[4], tup[5], tup[6] // 1000
    ).isoformat() + f"{tup[7]:+03d}:{abs(tup[8]):02d}"

conn_str = (
    f"DRIVER={{{os.getenv('SQL_SERVER_DRIVER')}}};"
    f"SERVER={os.getenv('SQL_SERVER_HOST')},{os.getenv('SQL_SERVER_PORT')};"
    f"DATABASE={os.getenv('SQL_SERVER_DB')};"
    f"UID={os.getenv('SQL_SERVER_USER')};"
    f"PWD={os.getenv('SQL_SERVER_PASSWORD')}"
)

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "backups", "xtracto_backup.sql")
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)


def sql_escape(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return f"'{value.isoformat()}'"
    if isinstance(value, bytes):
        return "0x" + value.hex()
    text = str(value).replace("'", "''")
    return f"'{text}'"


def get_create_table_sql(cur, schema, table):
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
               NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        schema,
        table,
    )
    cols = cur.fetchall()

    cur.execute(
        """
        SELECT ku.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
          ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
        WHERE tc.TABLE_SCHEMA = ? AND tc.TABLE_NAME = ? AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
        ORDER BY ku.ORDINAL_POSITION
        """,
        schema,
        table,
    )
    pk_cols = [r.COLUMN_NAME for r in cur.fetchall()]

    lines = []
    for c in cols:
        dtype = c.DATA_TYPE
        if dtype in ("varchar", "nvarchar", "char", "nchar"):
            length = "MAX" if c.CHARACTER_MAXIMUM_LENGTH == -1 else c.CHARACTER_MAXIMUM_LENGTH
            dtype_sql = f"{dtype}({length})"
        elif dtype in ("decimal", "numeric"):
            dtype_sql = f"{dtype}({c.NUMERIC_PRECISION},{c.NUMERIC_SCALE})"
        else:
            dtype_sql = dtype
        nullable = "NULL" if c.IS_NULLABLE == "YES" else "NOT NULL"
        default = f" DEFAULT {c.COLUMN_DEFAULT}" if c.COLUMN_DEFAULT else ""
        lines.append(f"    [{c.COLUMN_NAME}] {dtype_sql} {nullable}{default}")

    if pk_cols:
        pk_list = ", ".join(f"[{c}]" for c in pk_cols)
        lines.append(f"    CONSTRAINT [PK_{table}] PRIMARY KEY ({pk_list})")

    body = ",\n".join(lines)
    return f"CREATE TABLE [{schema}].[{table}] (\n{body}\n);\n"


def main():
    conn = pyodbc.connect(conn_str, timeout=30)
    conn.add_output_converter(-155, handle_datetimeoffset)
    cur = conn.cursor()

    cur.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
    )
    tables = [(r.TABLE_SCHEMA, r.TABLE_NAME) for r in cur.fetchall()]

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(f"-- Xtracto SQL Server backup\n-- Generated: {datetime.datetime.now().isoformat()}\n")
        f.write(f"-- Database: {os.getenv('SQL_SERVER_DB')}\n")
        f.write(f"-- Tables: {len(tables)}\n\n")

        for schema, table in tables:
            print(f"Dumping {schema}.{table} ...")
            f.write(f"\n-- ============================================\n")
            f.write(f"-- Table: {schema}.{table}\n")
            f.write(f"-- ============================================\n\n")
            f.write(f"DROP TABLE IF EXISTS [{schema}].[{table}];\nGO\n\n")
            f.write(get_create_table_sql(cur, schema, table))
            f.write("GO\n\n")

            cur.execute(f"SELECT * FROM [{schema}].[{table}]")
            col_names = [d[0] for d in cur.description]
            col_list = ", ".join(f"[{c}]" for c in col_names)
            row_count = 0
            rows = cur.fetchall()
            for row in rows:
                values = ", ".join(sql_escape(v) for v in row)
                f.write(f"INSERT INTO [{schema}].[{table}] ({col_list}) VALUES ({values});\n")
                row_count += 1
            f.write(f"\n-- {row_count} rows\nGO\n")
            print(f"  {row_count} rows")

    conn.close()
    print(f"\nBackup written to: {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    main()
