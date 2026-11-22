from decimal import Decimal

import pytest

from app import pricing


@pytest.mark.parametrize(
    "minutes, expected",
    [
        (0, 0),
        (1000, 0),      # all free
        (1001, 10),     # one started block
        (2000, 10),     # exactly one full block
        (2001, 20),
        (3500, 30),
    ],
)
def test_phone_charge(minutes, expected):
    assert pricing.phone_charge(minutes)[1] == Decimal(expected)


@pytest.mark.parametrize(
    "mb, expected",
    [
        (0, 50),        # base package is charged even with no usage
        (20_000, 50),   # exactly 20 GB
        (20_001, 60),   # 1 MB over starts a 10 GB block
        (30_000, 60),
        (35_000, 70),   # example from the assignment screen
        (41_250, 80),
    ],
)
def test_internet_charge(mb, expected):
    assert pricing.internet_charge(mb)[1] == Decimal(expected)


def test_calculate_total():
    c = pricing.calculate(1450, 35_000)
    assert c.phone_extra_blocks == 1
    assert c.internet_extra_blocks == 2
    assert c.total == Decimal(80)


def test_calculate_rejects_negative_usage():
    with pytest.raises(ValueError):
        pricing.calculate(-1, 0)
