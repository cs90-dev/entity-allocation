"""Database setup and session management."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

DEFAULT_DB_PATH = os.path.expanduser("~/.ceviche/ceviche.db")


def get_engine(db_path: str = None):
    """Create SQLAlchemy engine."""
    path = db_path or os.environ.get("CEVICHE_DB", DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def get_session(db_path: str = None):
    """Create a new database session."""
    engine = get_engine(db_path)
    Session = sessionmaker(bind=engine)
    return Session()


def init_db(db_path: str = None):
    """Initialize the database, creating all tables."""
    engine = get_engine(db_path)
    # Import all models to ensure they're registered with Base
    import ceviche.models.entities  # noqa: F401
    import ceviche.models.policies  # noqa: F401
    import ceviche.models.expenses  # noqa: F401
    import ceviche.models.allocations  # noqa: F401
    Base.metadata.create_all(engine)
    return engine
