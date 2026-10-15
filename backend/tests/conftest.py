import os
import tempfile
from pathlib import Path

# До импорта common.db: тесты работают на отдельной временной БД
_DB = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB.as_posix()}"
os.environ["REDIS_URL"] = ""
os.environ["TRAVELPAYOUTS_TOKEN"] = "test-token"

import pytest  # noqa: E402

import common.models  # noqa: E402,F401
from common.db import Base, engine  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
