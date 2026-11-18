import pytest
from fastapi.testclient import TestClient

from app.api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_phones(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["phones"] >= 5
    phones = client.get("/phones").json()
    assert len(phones) == h["phones"]
    detail = client.get("/phones/galaxy-s23").json()
    assert detail["name"] == "Samsung Galaxy S23" and detail["specifications"]
    assert client.get("/phones/nokia-3310").status_code == 404


def test_rankings_and_compare(client):
    r = client.get("/rankings/battery_mah?limit=3").json()
    vals = [x["value"] for x in r["results"]]
    assert vals == sorted(vals, reverse=True)
    assert client.get("/rankings/bogus").status_code == 400
    c = client.get("/compare", params={"phones": ["s23", "s22"]}).json()
    assert c["metrics"]["geekbench_score"]["best"] == ["Samsung Galaxy S23"]


def test_chat_and_batch(client):
    r = client.post("/chat", json={"question": "What is the screen size of the Galaxy S22?"}).json()
    assert "6.1" in r["answer"] and r["session_id"]
    batch = client.post("/chat/batch", json={"questions": [
        "How does the Galaxy S23 compare to the S22 in terms of performance?",
        "And what about their battery?",
    ]}).json()
    assert len(batch) == 2 and batch[0]["session_id"] == batch[1]["session_id"]
    assert batch[1]["phones"] == batch[0]["phones"]
    assert client.delete(f"/chat/{batch[0]['session_id']}").json()["cleared"] is True


def test_review_endpoint(client):
    r = client.post("/review", json={"phone": "Galaxy S22 Ultra", "focus": "camera"}).json()
    assert "Review" in r["review"] and len(r["agent_trace"]) >= 5
    assert client.post("/review", json={"phone": "Pixel 9"}).status_code == 404
