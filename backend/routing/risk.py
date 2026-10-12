"""Weather risk classification for a single checkpoint (rules from ASSIGNMENT.md).

The spec's bands share their endpoints (e.g. rain "0.10–0.25" Moderate and
"0.25–0.50" High), so each shared endpoint is resolved into the *higher* band,
which is also how the spec words its open ends ("<25 mph" Low, "≥55 mph"
No Travel). The two exceptions come straight from the spec: rain and snow
are only No Travel when strictly *above* the Severe band's top (">1.00",
">3.0"), so 1.00 in/hr rain and 3.0 in/hr snow are still Severe.

    Wind (mph):     <25 Low | 25–<35 Moderate | 35–<45 High | 45–<55 Severe | ≥55 No Travel
    Rain (in/hr):   <0.10 Low | 0.10–<0.25 Moderate | 0.25–<0.50 High | 0.50–1.00 Severe | >1.00 No Travel
    Snow (in/hr):   <0.5 Low | 0.5–<1.0 Moderate | 1.0–<2.0 High | 2.0–3.0 Severe | >3.0 No Travel

Load rules adjust the wind level only:
    ≥55 mph                      -> No Travel for any load
    45–<55 mph and >30,000 lb    -> No Travel
    35–<45 mph and >40,000 lb    -> Severe
"""

from dataclasses import dataclass
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


def wind_level(mph: float) -> RiskLevel:
    if mph >= 55:
        return RiskLevel.NO_TRAVEL
    if mph >= 45:
        return RiskLevel.SEVERE
    if mph >= 35:
        return RiskLevel.HIGH
    if mph >= 25:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def rain_level(in_per_hr: float) -> RiskLevel:
    if in_per_hr > 1.00:
        return RiskLevel.NO_TRAVEL
    if in_per_hr >= 0.50:
        return RiskLevel.SEVERE
    if in_per_hr >= 0.25:
        return RiskLevel.HIGH
    if in_per_hr >= 0.10:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def snow_level(in_per_hr: float) -> RiskLevel:
    if in_per_hr > 3.0:
        return RiskLevel.NO_TRAVEL
    if in_per_hr >= 2.0:
        return RiskLevel.SEVERE
    if in_per_hr >= 1.0:
        return RiskLevel.HIGH
    if in_per_hr >= 0.5:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def loaded_wind_level(mph: float, weight_lb: float) -> RiskLevel:
    """Wind level after applying the load rules. Load can only raise the level."""
    base = wind_level(mph)
    if 45 <= mph < 55 and weight_lb > 30_000:
        return RiskLevel.NO_TRAVEL
    if 35 <= mph < 45 and weight_lb > 40_000:
        return max(base, RiskLevel.SEVERE)
    return base


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    factor: str | None
    """Condition that set the level ("wind", "rain" or "snow"); None when all are Low."""
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    load_adjusted: bool
    """True when a load rule raised the wind level above its weather-only level."""


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, weight_lb: float) -> RiskAssessment:
    """Classify one checkpoint: the overall level is the worst of wind, rain and snow."""
    wind = loaded_wind_level(wind_mph, weight_lb)
    rain = rain_level(rain_in_hr)
    snow = snow_level(snow_in_hr)

    # Ties go to the first condition in the spec's table order: wind, rain, snow.
    factor, level = max((("wind", wind), ("rain", rain), ("snow", snow)), key=lambda item: item[1])
    return RiskAssessment(
        level=level,
        factor=factor if level > RiskLevel.LOW else None,
        wind=wind,
        rain=rain,
        snow=snow,
        load_adjusted=wind > wind_level(wind_mph),
    )
