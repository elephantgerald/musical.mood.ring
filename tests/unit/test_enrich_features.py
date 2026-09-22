"""
Unit tests for the AcousticBrainz high-level parse in musical-mash-bill.

Guards issue #70: the enricher used to read `highlevel[key]["probability"]`,
which is the classifier's confidence in whichever label WON — not the
probability of the mood being named. Because confidence sits near 1.0 almost
always, every stored feature came out large regardless of the track, and all
eight mood zones collapsed onto a single point in (valence, energy) space.
"""
import sys
from pathlib import Path

import pytest

# The pipeline scripts are not a package; make this one importable as conftest
# does for the firmware modules.
_SCRIPTS = Path(__file__).parent.parent.parent / "src" / "musical-mash-bill" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import enrich_features as ef


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def classifier(winner: str, loser: str, winner_p: float):
    """One AcousticBrainz high-level entry, in the API's real shape."""
    return {
        "value": winner,
        "probability": winner_p,
        "all": {winner: winner_p, loser: round(1.0 - winner_p, 12)},
    }


# Cocteau Twins — "Lazy Calm", as the live API returns it. Every classifier
# here is confident, but most of them are confident about the NEGATIVE label.
LAZY_CALM = {
    "highlevel": {
        "mood_happy":      classifier("not_happy",      "happy",          0.822899),
        "mood_sad":        classifier("sad",            "not_sad",        0.5),
        "mood_aggressive": classifier("not_aggressive", "aggressive",     0.999991),
        "mood_relaxed":    classifier("relaxed",        "not_relaxed",    1.0),
        "mood_acoustic":   classifier("acoustic",       "not_acoustic",   0.987600),
        "mood_party":      classifier("not_party",      "party",          0.998),
        "mood_electronic": classifier("not_electronic", "electronic",     0.832),
        "danceability":    classifier("not_danceable",  "danceable",      0.984451),
    }
}


@pytest.fixture
def fetch(monkeypatch):
    """Call ab_fetch_hl against a canned payload instead of the network."""
    def _fetch(payload, status_code=200):
        monkeypatch.setattr(
            ef.requests, "get",
            lambda *a, **kw: FakeResponse(payload, status_code),
        )
        return ef.ab_fetch_hl("any-mbid")
    return _fetch


def test_reads_the_positive_label_not_the_winner(fetch):
    # The bug: every one of these would have come back ≈ the winner's
    # confidence. mood_aggressive stored 1.0 when the truth is ~0.0.
    hl = fetch(LAZY_CALM)
    assert hl["mood_aggressive"] == pytest.approx(0.0,    abs=5e-5)
    assert hl["mood_happy"]      == pytest.approx(0.1771, abs=5e-5)
    assert hl["mood_party"]      == pytest.approx(0.002,  abs=5e-5)


def test_winning_positive_label_is_kept_as_is(fetch):
    # When the positive label wins, its probability IS the value we want —
    # the old code was right by accident exactly here, which is why the bug hid.
    hl = fetch(LAZY_CALM)
    assert hl["mood_relaxed"]  == pytest.approx(1.0,    abs=5e-5)
    assert hl["mood_acoustic"] == pytest.approx(0.9876, abs=5e-5)


def test_danceability_reads_the_danceable_label(fetch):
    # The one key whose positive label is not its own name.
    hl = fetch(LAZY_CALM)
    assert hl["danceability"] == pytest.approx(0.0155, abs=5e-5)


def test_opposing_moods_are_not_both_high(fetch):
    # The tell that needed no API call: a track cannot be both fully
    # aggressive and fully relaxed. Under the bug, this track was.
    hl = fetch(LAZY_CALM)
    assert hl["mood_aggressive"] + hl["mood_relaxed"] <= 1.5
    assert hl["mood_happy"] + hl["mood_sad"] <= 1.5


def test_every_documented_feature_is_returned(fetch):
    hl = fetch(LAZY_CALM)
    assert set(hl) == set(ef.AB_POSITIVE_LABEL)


def test_missing_classifier_is_none_not_zero(fetch):
    # A partial payload must not silently read as "this mood is absent".
    partial = {"highlevel": {"mood_happy": classifier("happy", "not_happy", 0.9)}}
    hl = fetch(partial)
    assert hl["mood_happy"] == pytest.approx(0.9, abs=5e-5)
    assert hl["mood_sad"] is None
    assert hl["danceability"] is None


def test_404_returns_none(fetch):
    assert fetch({}, status_code=404) is None
