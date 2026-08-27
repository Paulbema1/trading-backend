"""
Connexion à la base de données via SQLAlchemy.
"""

from sqlalchemy import create_engine
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
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import src.models.user
    import src.models.signal
    import src.models.system_config

    # Crée les tables sans jamais les supprimer (Conservation permanente des données)
    Base.metadata.create_all(bind=engine)
    print("✅ Base de données initialisée (Comptes et Signaux conservés).")
