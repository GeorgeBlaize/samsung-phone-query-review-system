import os
import tempfile
from pathlib import Path

# Configure before any app module is imported (settings are read at import time).
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"
os.environ["LLM_PROVIDER"] = "none"
os.environ["EMBEDDING_BACKEND"] = "tfidf"

import pytest  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.db.repository import load_json  # noqa: E402
from app.db.session import SessionLocal, get_session, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    init_db()
    with get_session() as s:
        load_json(s, DATA_DIR / "phones.json")
    yield


@pytest.fixture(scope="session")
def bot(seeded_db):
    from app.rag.chatbot import ChatBot

    return ChatBot(SessionLocal, use_llm=False)
