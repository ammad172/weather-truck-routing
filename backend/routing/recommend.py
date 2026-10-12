"""Route summaries and the recommendation (preference order from ASSIGNMENT.md).

Routes are compared criterion by criterion, moving to the next only on a tie:

    0. Fewest No Travel miles   (not in the spec's list, but strictly worse than Severe)
    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk      (distance-weighted, 0 = all Low ... 4 = all No Travel)
    4. Shortest travel time

Miles are compared at 0.1 mi and average risk at 0.01, so float noise between
otherwise equal routes doesn't decide the result and the tie falls through to
the next criterion.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .risk import RiskLevel


@dataclass(frozen=True)
class RouteSummary:
    route_id: str
    distance_mi: float
    duration_s: float
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    avg_risk: float
    worst_level: RiskLevel


@dataclass(frozen=True)
class Recommendation:
    route_id: str
    ranking: list[str]
    """Route ids, best first."""
    reason: str
    warning: str | None


def summarize_route(
    route_id: str,
    segments: Iterable[tuple[float, RiskLevel]],
    distance_mi: float,
    duration_s: float,
) -> RouteSummary:
    """Summarize a route from its checkpoints' (segment_miles, level) pairs."""
    miles_at = {level: 0.0 for level in RiskLevel}
    weighted = total = 0.0
    for miles, level in segments:
        miles_at[level] += miles
        weighted += miles * level
        total += miles
    if total <= 0:
        raise ValueError("A route summary needs at least one segment with positive length.")
    return RouteSummary(
        route_id=route_id,
        distance_mi=distance_mi,
        duration_s=duration_s,
        no_travel_miles=miles_at[RiskLevel.NO_TRAVEL],
        severe_miles=miles_at[RiskLevel.SEVERE],
        high_miles=miles_at[RiskLevel.HIGH],
        avg_risk=weighted / total,
        worst_level=max(level for level in RiskLevel if miles_at[level] > 0),
    )


def format_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60}h {minutes % 60:02d}m"


@dataclass(frozen=True)
class _Criterion:
    name: str
    key: Callable[[RouteSummary], float]
    show: Callable[[RouteSummary], str]
    decides: str
    """Phrase used when this criterion decided the recommendation."""


_CRITERIA = (
    _Criterion("No Travel miles", lambda s: round(s.no_travel_miles, 1), lambda s: f"{s.no_travel_miles:.1f} mi", "fewest No Travel miles"),
    _Criterion("Severe miles", lambda s: round(s.severe_miles, 1), lambda s: f"{s.severe_miles:.1f} mi", "fewest Severe miles"),
    _Criterion("High miles", lambda s: round(s.high_miles, 1), lambda s: f"{s.high_miles:.1f} mi", "fewest High miles"),
    _Criterion("average risk", lambda s: round(s.avg_risk, 2), lambda s: f"{s.avg_risk:.2f}", "lowest average risk"),
    _Criterion("travel time", lambda s: s.duration_s, lambda s: format_duration(s.duration_s), "shortest travel time"),
)


def ranking_key(summary: RouteSummary) -> tuple[float, ...]:
    return tuple(c.key(summary) for c in _CRITERIA)


def recommend(summaries: Sequence[RouteSummary]) -> Recommendation:
    if not summaries:
        raise ValueError("Nothing to recommend: no routes.")

    ranked = sorted(summaries, key=ranking_key)  # stable: equal routes keep provider order
    best = ranked[0]
    warning = (
        "Every route crosses No Travel conditions. Consider a later departure."
        if best.no_travel_miles > 0
        else None
    )
    return Recommendation(
        route_id=best.route_id,
        ranking=[s.route_id for s in ranked],
        reason=_reason(best, ranked[1]) if len(ranked) > 1 else "Only route available.",
        warning=warning,
    )


def _reason(best: RouteSummary, runner_up: RouteSummary) -> str:
    """Explain the win over the runner-up using the first criterion that differed."""
    other = f"Route {runner_up.route_id}"
    for i, criterion in enumerate(_CRITERIA):
        if criterion.key(best) != criterion.key(runner_up):
            decided = f"{criterion.decides}: {criterion.show(best)} vs {criterion.show(runner_up)} on {other}."
            # No Travel isn't one of the spec's criteria; only mention a tie on it when it's non-zero.
            tied = [c.name for c in _CRITERIA[:i] if c is not _CRITERIA[0] or best.no_travel_miles > 0]
            if not tied:
                return decided[0].upper() + decided[1:]
            return f"Tied with {other} on {_join(tied)}; {decided}"
    return f"Tied with {other} on every criterion; listed first."


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
