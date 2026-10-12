import pytest

from routing.risk import RiskLevel, assess, loaded_wind_level, rain_level, snow_level, wind_level

L, M, H, S, NT = RiskLevel


@pytest.mark.parametrize(
    ("mph", "expected"),
    [
        (0, L), (24.9, L),
        (25, M), (34.9, M),
        (35, H), (44.9, H),
        (45, S), (54.9, S),
        (55, NT), (80, NT),
    ],
)
def test_wind_bands(mph, expected):
    assert wind_level(mph) is expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0, L), (0.09, L),
        (0.10, M), (0.24, M),
        (0.25, H), (0.49, H),
        (0.50, S), (1.00, S),  # 1.00 is still Severe: No Travel is ">1.00"
        (1.01, NT),
    ],
)
def test_rain_bands(rate, expected):
    assert rain_level(rate) is expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (0, L), (0.49, L),
        (0.5, M), (0.99, M),
        (1.0, H), (1.99, H),
        (2.0, S), (3.0, S),  # 3.0 is still Severe: No Travel is ">3.0"
        (3.01, NT),
    ],
)
def test_snow_bands(rate, expected):
    assert snow_level(rate) is expected


@pytest.mark.parametrize(
    ("mph", "weight", "expected"),
    [
        # >=55 mph is No Travel for any load
        (55, 0, NT),
        (55, 80_000, NT),
        # 45-54 mph: No Travel only above 30,000 lb
        (45, 30_000, S),
        (45, 30_001, NT),
        (54.9, 30_001, NT),
        (54.9, 30_000, S),
        # 35-44 mph: Severe only above 40,000 lb
        (35, 40_000, H),
        (35, 40_001, S),
        (44.9, 40_001, S),
        (44.9, 30_001, H),  # the 30k rule applies only to 45-54 mph
        # Below 35 mph, load never matters
        (34.9, 80_000, M),
        (10, 80_000, L),
    ],
)
def test_load_rules(mph, weight, expected):
    assert loaded_wind_level(mph, weight) is expected


def test_assess_takes_worst_condition():
    result = assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=1.5, weight_lb=20_000)
    assert result.level is H
    assert (result.wind, result.rain, result.snow) == (L, H, H)


def test_assess_tie_goes_to_first_condition_in_spec_order():
    result = assess(wind_mph=30, rain_in_hr=0.15, snow_in_hr=0.7, weight_lb=0)
    assert result.level is M
    assert result.factor == "wind"


def test_assess_reports_factor_and_load_adjustment():
    result = assess(wind_mph=47, rain_in_hr=0.0, snow_in_hr=0.0, weight_lb=35_000)
    assert result.level is NT
    assert result.factor == "wind"
    assert result.load_adjusted


def test_assess_snow_driven_checkpoint_is_not_load_adjusted():
    result = assess(wind_mph=5, rain_in_hr=0.0, snow_in_hr=2.5, weight_lb=79_000)
    assert result.level is S
    assert result.factor == "snow"
    assert not result.load_adjusted


def test_assess_all_low_has_no_factor():
    result = assess(wind_mph=5, rain_in_hr=0.0, snow_in_hr=0.0, weight_lb=40_000)
    assert result.level is L
    assert result.factor is None


def test_level_labels():
    assert [level.label for level in RiskLevel] == ["Low", "Moderate", "High", "Severe", "No Travel"]
