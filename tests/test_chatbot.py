from types import SimpleNamespace

from app.rag.aspects import detect_aspects, detect_ranking
from app.rag.entities import PhoneMatcher


def _phones(*names):
    return [SimpleNamespace(name=n) for n in names]


def test_entity_matching_prefers_longest_alias():
    m = PhoneMatcher(_phones("Samsung Galaxy S23", "Samsung Galaxy S23 Ultra", "Samsung Galaxy S22+ 5G",
                             "Samsung Galaxy Z Fold5"))
    assert [p.name for p in m.find("s23 ultra vs s23")] == ["Samsung Galaxy S23 Ultra", "Samsung Galaxy S23"]
    assert [p.name for p in m.find("Galaxy S22 plus")] == ["Samsung Galaxy S22+ 5G"]
    assert [p.name for p in m.find("is the fold 5 good")] == ["Samsung Galaxy Z Fold5"]
    assert m.find("s23 fe") == []  # FE not in this catalogue -> must not fall back to plain S23


def test_aspect_and_ranking_detection():
    assert [a.name for a in detect_aspects("What are the camera specs?")] == ["camera"]
    assert detect_ranking("Which phone has the best battery life?") is False  # descending
    assert detect_ranking("cheapest phone") is True


def test_sample_query_camera_specs(bot):
    r = bot.ask("What are the camera specs of the Samsung Galaxy S23?")
    assert r.intent == "spec_lookup" and r.phones == ["Samsung Galaxy S23"]
    assert "50 MP" in r.answer and "Selfie" in r.answer


def test_sample_query_best_battery(bot):
    r = bot.ask("Which Samsung phone has the best battery life?")
    assert r.intent == "ranking" and "battery" in r.aspects
    assert "RANKING" in r.context and "Endurance" in r.context or "endurance" in r.context


def test_sample_query_comparison_and_follow_up(bot):
    r = bot.ask("How does the Galaxy S23 compare to the S22 in terms of performance?", "s1")
    assert r.intent == "comparison"
    assert r.phones == ["Samsung Galaxy S23", "Samsung Galaxy S22 5G"]
    assert "GeekBench" in r.answer
    follow = bot.ask("And what about their price?", "s1")
    assert follow.phones == r.phones and "price" in follow.aspects and "$" in follow.answer


def test_ranking_question_ignores_memory(bot):
    bot.ask("Tell me about the Galaxy S22", "s2")
    r = bot.ask("Which is the cheapest phone?", "s2")
    assert r.intent == "ranking" and r.phones == []


def test_catalog_and_unknown(bot):
    assert bot.ask("Which phones do you have?").intent == "catalog"
    r = bot.ask("Tell me about the Pixel 9")
    assert r.intent == "general"
