from sqlmodel import SQLModel, Session, create_engine
from core.config import settings

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})


def create_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
