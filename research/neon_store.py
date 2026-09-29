"""
Stockage des bougies historiques dans Neon, pour ne pas retélécharger à
chaque run. Table séparée de la prod (historical_candles) — aucun lien
avec les tables Signal/OpenPosition/User.
"""
import os
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd


def get_conn():
    dsn = os.environ["NEON_DATABASE_URL"]
    return psycopg2.connect(dsn)


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historical_candles (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                datetime TIMESTAMP NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                PRIMARY KEY (symbol, timeframe, datetime)
            )
        """)
    conn.commit()


def upsert_candles(conn, symbol: str, timeframe: str, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    rows = [
        (symbol, timeframe, row.datetime.to_pydatetime(),
         float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume))
        for row in df.itertuples()
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO historical_candles (symbol, timeframe, datetime, open, high, low, close, volume)
            VALUES %s
            ON CONFLICT (symbol, timeframe, datetime) DO NOTHING
        """, rows, page_size=1000)
    conn.commit()
    return len(rows)


def load_candles(conn, symbol: str, timeframe: str) -> pd.DataFrame:
    query = """
        SELECT datetime, open, high, low, close, volume
        FROM historical_candles
        WHERE symbol = %s AND timeframe = %s
        ORDER BY datetime
    """
    return pd.read_sql(query, conn, params=(symbol, timeframe))


def restore_local_parquet(conn, symbol: str, timeframe: str) -> bool:
    """Recopie ce qui est stocké dans Neon vers le fichier Parquet local
    attendu par historical_data_manager, pour que le moteur de backtest
    (jamais modifié) puisse le lire normalement."""
    from src.backtest.historical_data import historical_data_manager
    df = load_candles(conn, symbol, timeframe)
    if df.empty:
        return False
    df["datetime"] = pd.to_datetime(df["datetime"])
    historical_data_manager.save_data(symbol, timeframe, df)
    print(f"  ♻️  {symbol} ({timeframe}) restauré depuis Neon : {len(df)} bougies")
    return True
