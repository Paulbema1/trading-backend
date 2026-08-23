"""
Connexion à la base de données via SQLAlchemy.

Supporte :
- SQLite (local / dev)
- PostgreSQL (Render / production)

Reconstruction propre et synchronisation du schéma.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from src.core.config import DATABASE_URL

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
    Reconstruit les tables PostgreSQL proprement.
    """
    # Import obligatoire des modèles pour enregistrer les métadonnées
    import src.models.user
    import src.models.signal

    # Sur PostgreSQL Render : Suppression forcée et validée de l'ancien schéma
    if not DATABASE_URL.startswith("sqlite"):
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS signals CASCADE;"))
                conn.execute(text("DROP TABLE IF EXISTS users CASCADE;"))
            print("✅ Ancien schéma PostgreSQL réinitialisé avec succès.")
        except Exception as e:
            print(f"Note réinitialisation PostgreSQL : {e}")

    # Création des nouvelles tables avec TOUTES les colonnes (role, fcm_token, etc.)
    Base.metadata.create_all(bind=engine)
    print("✅ Nouvelles tables PostgreSQL créées avec succès.")
