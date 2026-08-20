"""
Connexion à la base de données via SQLAlchemy.

Supporte :
- SQLite (local / dev)
- PostgreSQL (Render / production)

L'URL est lue depuis config.DATABASE_URL.
"""

from sqlalchemy import create_engine
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
    """
    Dépendance FastAPI.

    Usage dans une route :
        @app.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Crée toutes les tables si elles n'existent pas.

    À appeler au démarrage de l'application.
    """
    Base.metadata.create_all(bind=engine)