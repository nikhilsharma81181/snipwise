import os

import pytest
from dotenv import load_dotenv

# Load .env, then point the app at the test DB before src is imported,
# so tests can never touch the dev database
load_dotenv()
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    # Calls the app in memory, no real server or port needed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
