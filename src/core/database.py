"""
Connexion à la base de données via SQLAlchemy.

Supporte :
- SQLite (local / dev)
- PostgreSQL (Render / production)

Initialisation et synchronisation automatique du schéma.
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
    S'assure que la structure des tables PostgreSQL est 100 % conforme.
    """
    # Import des modèles pour enregistrer les métadonnées
    import src.models.user
    import src.models.signal

    # Nettoyage automatique des anciennes tables obsolètes sur PostgreSQL
    if not DATABASE_URL.startswith("sqlite"):
        try:
            with engine.connect() as conn:
                check_query = text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='users' AND column_name='role';"
                )
                res = conn.execute(check_query).fetchone()
                if not res:
                    print("⚠️ Ancien schéma PostgreSQL détecté : Réinitialisation propre...")
                    conn.execute(text("DROP TABLE IF EXISTS signals CASCADE;"))
                    conn.execute(text("DROP TABLE IF EXISTS users CASCADE;"))
                    conn.commit()
                    print("✅ Ancien schéma réinitialisé.")
        except Exception as e:
            print(f"Note vérification PostgreSQL : {e}")

    # Création des nouvelles tables complètes
    Base.metadata.create_all(bind=engine)
    print("✅ Tables de la base de données initialisées avec succès.")
