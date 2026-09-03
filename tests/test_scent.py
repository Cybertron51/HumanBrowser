"""Invariants of the scent models.

M-004 showed `choose` carries the whole gate effect, and choose is
`scent x visibility`. This is the load-bearing half.

    pytest -m "not model"    # skip the ones needing a model download
"""
from __future__ import annotations

import pytest

from humanbrowser import scent as S

from conftest import element

# A goal phrased the way someone who does not know the feature's name would ask.
USER_GOAL = "I run this same search every week, can I keep it"
PAGE = [element("Provisioning", "/provisioning.html"),
        element("Shipping", "/shipping.html"),
        element("Support", "/support.html"),
        element("Shop", "/shop.html")]


@pytest.fixture(scope="module")
def embedding():
    pytest.importorskip("sentence_transformers")
    return S.EmbeddingScent()


# -- contract both models must satisfy ----------------------------------------

@pytest.fixture(params=["keyword", "embedding"])
def model(request, embedding):
    return S.KeywordScent() if request.param == "keyword" else embedding


def test_one_score_per_element(model):
    assert len(model.score("anything", PAGE)) == len(PAGE)


def test_scores_are_in_the_unit_interval(model):
    """score = scent x visibility, and visibility is [0,1]. A scent outside
    [0,1] would let an element outrank a perfectly visible perfect match, or go
    negative and inverert the gate."""
    for goal in (USER_GOAL, "shop", "", "   ", "qwertyuiop zxcvbnm"):
        assert all(0.0 <= s <= 1.0 for s in model.score(goal, PAGE))


def test_an_empty_goal_has_no_scent(model):
    assert model.score("", PAGE) == [0.0] * len(PAGE)


def test_an_empty_page_is_handled(model):
    assert model.score(USER_GOAL, []) == []


def test_scoring_is_deterministic(model):
    assert model.score(USER_GOAL, PAGE) == model.score(USER_GOAL, PAGE)


def test_an_unlabelled_element_has_no_scent(model):
    assert model.score("find the thing", [element("", None)])[0] == 0.0


# -- keyword ------------------------------------------------------------------

def test_quoting_the_label_scores_the_maximum():
    assert S.KeywordScent().score("shop the collection",
                                  [element("Shop the collection", "/shop")])[0] == 1.0


def test_partial_overlap_scores_a_fraction():
    s = S.KeywordScent().score("shop the collection", [element("Shop", "/shop")])[0]
    assert s == pytest.approx(0.5)


def test_keyword_scent_is_flat_for_a_user_phrased_goal():
    """D-007, as a test. Every score is 0, so softmax is uniform and the
    visibility gate has nothing to modulate. This is why M4 blocks M2."""
    scores = S.KeywordScent().score(USER_GOAL, PAGE)
    assert scores == [0.0] * len(PAGE)
    assert len(set(scores)) == 1


# -- embedding ----------------------------------------------------------------

@pytest.mark.model
def test_embedding_scent_is_not_flat_for_the_same_goal(embedding):
    """The whole point of M4: give the gate something to weight."""
    scores = embedding.score(USER_GOAL, PAGE)
    assert len(set(scores)) > 1
    assert max(scores) - min(scores) > 0.02


@pytest.mark.model
def test_a_related_label_outranks_an_unrelated_one(embedding):
    els = [element("Save this search", "/save"), element("Privacy policy", "/privacy")]
    related, unrelated = embedding.score(USER_GOAL, els)
    assert related > unrelated


@pytest.mark.model
def test_paraphrase_beats_word_overlap_with_the_wrong_meaning(embedding):
    """Keyword scent cannot tell these apart; that is the gap being closed."""
    els = [element("Keep this search", "/a"), element("Search and rescue", "/b")]
    keep, rescue = embedding.score("save a search I run often", els)
    assert keep > rescue


@pytest.mark.model
def test_scores_are_never_negative(embedding):
    """Cosine is [-1,1]; a negative would invert the gate, making a faint
    irrelevant link outrank a prominent irrelevant one."""
    els = [element(t, "/x") for t in
           ("Privacy policy", "Terms and conditions", "asdfgh qwerty", "1234")]
    assert all(s >= 0.0 for s in embedding.score(USER_GOAL, els))


@pytest.mark.model
def test_the_cache_does_not_change_answers(embedding):
    first = embedding.score(USER_GOAL, PAGE)
    embedding.score("an unrelated goal entirely", PAGE)     # populates more cache
    assert embedding.score(USER_GOAL, PAGE) == first


# -- selection ----------------------------------------------------------------

def test_get_returns_the_named_model():
    assert S.get("keyword").name == "keyword"


def test_get_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown scent model"):
        S.get("word2vec")


def test_element_text_uses_name_and_href():
    t = S.element_text(element("Provisioning", "/provisioning.html"))
    assert "Provisioning" in t and "provisioning.html" in t
