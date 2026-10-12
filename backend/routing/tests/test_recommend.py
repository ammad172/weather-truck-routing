import pytest

from routing.recommend import RouteSummary, format_duration, recommend, summarize_route
from routing.risk import RiskLevel

L, M, H, S, NT = RiskLevel


def route(route_id, *, no_travel=0.0, severe=0.0, high=0.0, avg=0.0, hours=10.0) -> RouteSummary:
    return RouteSummary(
        route_id=route_id,
        distance_mi=600,
        duration_s=hours * 3600,
        no_travel_miles=no_travel,
        severe_miles=severe,
        high_miles=high,
        avg_risk=avg,
        worst_level=L,
    )


def test_summarize_route_counts_miles_by_level_and_weights_average():
    summary = summarize_route("A", [(25, L), (50, H), (25, S)], distance_mi=100, duration_s=6000)
    assert summary.high_miles == 50
    assert summary.severe_miles == 25
    assert summary.no_travel_miles == 0
    assert summary.avg_risk == pytest.approx((0 * 25 + 2 * 50 + 3 * 25) / 100)
    assert summary.worst_level is S


def test_summarize_route_rejects_empty_segments():
    with pytest.raises(ValueError):
        summarize_route("A", [], distance_mi=0, duration_s=0)


def test_fewest_severe_miles_beats_everything_below_it():
    fast_but_severe = route("A", severe=10, high=0, avg=0.1, hours=8)
    slow_but_safe = route("B", severe=0, high=200, avg=2.0, hours=14)
    result = recommend([fast_but_severe, slow_but_safe])
    assert result.route_id == "B"
    assert result.reason == "Fewest Severe miles: 0.0 mi vs 10.0 mi on Route A."


def test_high_miles_break_a_severe_tie():
    result = recommend([route("A", severe=5, high=40), route("B", severe=5, high=10)])
    assert result.route_id == "B"
    assert result.reason == "Tied with Route A on Severe miles; fewest High miles: 10.0 mi vs 40.0 mi on Route A."


def test_reason_mentions_a_no_travel_tie_only_when_non_zero():
    result = recommend([route("A", no_travel=5, severe=8), route("B", no_travel=5, severe=2)])
    assert result.reason.startswith("Tied with Route A on No Travel miles; fewest Severe miles")


def test_average_risk_breaks_a_severe_and_high_tie():
    result = recommend([route("A", avg=1.2), route("B", avg=0.8)])
    assert result.route_id == "B"
    assert "lowest average risk: 0.80 vs 1.20 on Route A" in result.reason


def test_travel_time_is_the_last_tie_breaker():
    result = recommend([route("A", hours=11), route("B", hours=10), route("C", hours=12)])
    assert result.ranking == ["B", "A", "C"]
    assert "shortest travel time: 10h 00m vs 11h 00m on Route A" in result.reason


def test_no_travel_miles_rank_worse_than_severe_miles():
    blocked = route("A", no_travel=5, severe=0)
    severe = route("B", no_travel=0, severe=100)
    result = recommend([blocked, severe])
    assert result.route_id == "B"
    assert result.warning is None


def test_warning_when_every_route_has_no_travel_miles():
    result = recommend([route("A", no_travel=30), route("B", no_travel=10)])
    assert result.route_id == "B"
    assert result.warning is not None


def test_float_noise_does_not_decide_the_ranking():
    # 0.04 mi of "extra" Severe on A is float noise, so the faster route should win on time.
    result = recommend([route("A", severe=10.04, hours=9), route("B", severe=10.0, hours=10)])
    assert result.route_id == "A"


def test_full_tie_keeps_input_order():
    result = recommend([route("A"), route("B")])
    assert result.ranking == ["A", "B"]
    assert result.reason == "Tied with Route B on every criterion; listed first."


def test_single_route():
    result = recommend([route("A")])
    assert result.route_id == "A"
    assert result.reason == "Only route available."


def test_no_routes_raises():
    with pytest.raises(ValueError):
        recommend([])


def test_format_duration():
    assert format_duration(6 * 3600 + 5 * 60 + 20) == "6h 05m"
