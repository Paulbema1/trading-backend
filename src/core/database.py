"""
Connexion à la base de données via SQLAlchemy.
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from src.core.config import DATABASE_URL
from src.core.logging import get_logger

logger = get_logger(__name__)

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
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_column(table_name: str, column_name: str, ddl_type: str) -> None:
    """
    Ajoute une colonne manquante sur une table déjà existante (migration légère).

    Base.metadata.create_all() crée les tables qui n'existent pas encore, mais
    n'altère JAMAIS une table déjà existante pour y ajouter une nouvelle colonne.
    Sur une base déjà en production (créée avant l'ajout de signal_id), ceci
    évite un crash "column does not exist" à chaque requête. Compatible
    SQLite et PostgreSQL. N'affecte aucune donnée existante ni aucune règle
    métier — pure maintenance de schéma.
    """
    try:
        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            return  # La table sera créée par create_all(), rien à faire ici.

        existing_columns = [c["name"] for c in inspector.get_columns(table_name)]
        if column_name in existing_columns:
            return  # Déjà présente, rien à faire.

        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}"))
        logger.info(f"Migration : colonne {table_name}.{column_name} ajoutée.")
    except Exception as e:
        logger.warning(f"Migration {table_name}.{column_name} ignorée ({e}).")


def init_db():
    import src.models.user
    import src.models.signal
    import src.models.system_config
    import src.models.position

    # Crée les tables qui n'existent pas encore (Conservation permanente des données)
    Base.metadata.create_all(bind=engine)

    # Ajoute les colonnes manquantes sur les tables déjà existantes en production
    # (voir _ensure_column ci-dessus).
    _ensure_column("signals", "signal_id", "VARCHAR(36)")

    print("✅ Base de données initialisée (Comptes et Signaux conservés).")
