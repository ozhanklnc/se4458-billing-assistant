"""Bill calculation rules.

Kept as plain functions (no DB access) so they can be unit tested directly.

Phone:    first 1,000 minutes are free, then $10 for every *started* block of 1,000 minutes.
Internet: flat $50 covers up to 20 GB, then $10 for every *started* block of 10 GB.
          1 GB = 1,000 MB (assignment definition, not 1,024).
"""
from dataclasses import dataclass
from decimal import Decimal

from .config import Settings, get_settings


def _started_blocks(amount_over: int, block_size: int) -> int:
    # ceil division without floats: 1 MB over the limit already starts a new block
    if amount_over <= 0:
        return 0
    return -(-amount_over // block_size)


@dataclass(frozen=True)
class Charges:
    phone_minutes: int
    internet_mb: int
    phone_extra_blocks: int
    internet_extra_blocks: int
    phone_charge: Decimal
    internet_charge: Decimal

    @property
    def total(self) -> Decimal:
        return self.phone_charge + self.internet_charge


def phone_charge(minutes: int, s: Settings | None = None) -> tuple[int, Decimal]:
    s = s or get_settings()
    blocks = _started_blocks(minutes - s.free_phone_minutes, s.phone_block_minutes)
    return blocks, Decimal(blocks * s.phone_block_price)


def internet_charge(mb: int, s: Settings | None = None) -> tuple[int, Decimal]:
    s = s or get_settings()
    blocks = _started_blocks(mb - s.internet_included_mb, s.internet_block_mb)
    return blocks, Decimal(s.internet_base_price + blocks * s.internet_block_price)


def calculate(minutes: int, mb: int, s: Settings | None = None) -> Charges:
    if minutes < 0 or mb < 0:
        raise ValueError("usage cannot be negative")
    p_blocks, p_charge = phone_charge(minutes, s)
    i_blocks, i_charge = internet_charge(mb, s)
    return Charges(minutes, mb, p_blocks, i_blocks, p_charge, i_charge)
