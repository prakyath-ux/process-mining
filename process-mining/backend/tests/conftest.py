import base64
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Configure an isolated DB *before* the app is imported (engine is built at import).
_tmpdir = tempfile.mkdtemp(prefix="pm_test_")
os.environ["PM_DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["PM_SEED_ADMIN_EMAIL"] = "admin@test.local"
os.environ["PM_SEED_ADMIN_PASSWORD"] = "admin12345"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    resp = client.post(
        "/api/auth/login",
        data={"username": "admin@test.local", "password": "admin12345"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


SMALL_CSV = """case_id,activity,timestamp,amount
C1,Application Received,2025-01-01 09:00:00,10000
C1,Credit Check,2025-01-01 11:00:00,10000
C1,Approved,2025-01-02 09:00:00,10000
C1,Closed,2025-01-03 09:00:00,10000
C2,Application Received,2025-01-01 10:00:00,20000
C2,Credit Check,2025-01-01 12:00:00,20000
C2,Rejected,2025-01-02 10:00:00,20000
C2,Closed,2025-01-03 10:00:00,20000
C3,Application Received,2025-01-02 09:00:00,30000
C3,Credit Check,2025-01-02 10:00:00,30000
C3,Approved,2025-01-04 09:00:00,30000
C3,Closed,2025-01-05 09:00:00,30000
"""


@pytest.fixture()
def uploaded_log(client, auth_headers):
    """Upload the small CSV fixture and return the created log id."""
    resp = client.post(
        "/api/ingest/file",
        headers=auth_headers,
        files={"file": ("test.csv", SMALL_CSV.encode(), "text/csv")},
        data={
            "name": "test-log",
            "case_col": "case_id",
            "activity_col": "activity",
            "timestamp_col": "timestamp",
            "attr_columns": "amount",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["log_id"]


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
