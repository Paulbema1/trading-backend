"""
Connexion à la base de données via SQLAlchemy.

Supporte :
- SQLite (local / dev)
- PostgreSQL (Render / production)

Met à jour automatiquement le schéma de la base de données (auto-migration).
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from src.core.config import DATABASE_URL

# SQLite nécessite check_same_thread=False
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """Dépendance FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Crée toutes les tables et s'assure que la structure PostgreSQL est à jour.
    """
    Base.metadata.create_all(bind=engine)

    # Auto-migration PostgreSQL pour ajouter les colonnes manquantes
    if not DATABASE_URL.startswith("sqlite"):
        try:
            with engine.connect() as conn:
                # Table Users
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(10) DEFAULT 'USER';"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS fcm_token VARCHAR(500);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT TRUE;"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_assets VARCHAR(200) DEFAULT 'EUR/USD,GBP/USD,USD/JPY,XAU/USD';"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"))

                # Table Signals
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS stop_loss DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS take_profit_1 DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS take_profit_2 DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS take_profit_3 DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS risk_reward DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS main_timeframe VARCHAR(10);"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS confirmation_timeframe VARCHAR(10);"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS score_breakdown TEXT;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS news_used BOOLEAN DEFAULT FALSE;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS news_status VARCHAR(30);"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS news_summary TEXT;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS data_quality VARCHAR(10) DEFAULT 'GOOD';"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_confirmed BOOLEAN;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS ai_reason TEXT;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS reasons TEXT;"))
                conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"))

                conn.commit()
                print("Migration PostgreSQL exécutée avec succès !")
        except Exception as e:
            print(f"Erreur migration PostgreSQL : {e}")
