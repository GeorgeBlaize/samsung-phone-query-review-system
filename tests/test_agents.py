from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.agents.review_graph import generate_review


def test_review_pipeline_template_mode():
    r = generate_review("Galaxy S23")
    assert r["error"] is None and r["phones"] == ["Samsung Galaxy S23"]
    agents = [t["agent"] for t in r["agent_trace"]]
    assert agents == ["Coordinator", "Spec Retriever", "Market Analyst", "Review Writer", "Fact Checker"]
    assert "# Samsung Galaxy S23 Review" in r["review"]
    assert r["unsupported_claims"] == []  # template uses only DB numbers
    assert r["analysis"][0]["overall_score"] is not None


def test_review_unknown_phone():
    r = generate_review("iPhone 15 Pro")
    assert r["error"] and r["review"] is None


def test_fact_checker_sends_hallucinated_draft_back():
    llm = FakeListChatModel(responses=[
        "# Review\nIt has a 9999 mAh battery and 3900 mAh is wrong.",   # hallucinated number
        "# Review\nIt has a 3900 mAh battery and a 50 MP main camera.",  # corrected draft
    ])
    r = generate_review("Galaxy S23", llm=llm)
    assert r["revisions"] == 1
    assert "9999" not in r["review"] and "3900 mAh" in r["review"]
    writer_steps = [t for t in r["agent_trace"] if t["agent"] == "Review Writer"]
    assert len(writer_steps) == 2


def test_comparative_review():
    r = generate_review("S23 vs S22")
    assert len(r["phones"]) == 2 and "Which should you buy?" in r["review"]
