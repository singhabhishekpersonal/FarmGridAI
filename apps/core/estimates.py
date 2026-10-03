"""Estimate data structures compatible with the standard API analytical block.

Every analytical value on the platform is an *estimate* carrying:
- a minimum/maximum/expected range
- currency
- a confidence level
- explicit assumptions and limitations
- confirmation/verification flags

See the response contract in ``solution.txt`` (analytical result block).
"""
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Union


@dataclass
class EstimateRange:
    minimum: Union[int, float]
    maximum: Union[int, float]
    expected: Union[int, float]
    currency: str = "INR"
    confidence: str = "low"  # low | medium | high
    assumptions: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    data_completeness: float = 0.0
    requires_farmer_confirmation: bool = True
    requires_official_verification: bool = False

    def __post_init__(self):
        if self.minimum > self.maximum:
            self.minimum, self.maximum = self.maximum, self.minimum

    def to_dict(self):
        base = asdict(self)
        base["estimate_type"] = "range"
        return base


def range_from_expected(expected, spread_frac=0.15, **kwargs):
    """Build an EstimateRange around an expected value with a +/- spread."""
    spread = abs(expected or 0) * spread_frac
    return EstimateRange(
        minimum=max(0, (expected or 0) - spread),
        maximum=(expected or 0) + spread,
        expected=expected or 0,
        **kwargs,
    )


def combine_ranges(ranges: List[EstimateRange]) -> EstimateRange:
    """Combine several ranges into one aggregate range."""
    if not ranges:
        return EstimateRange(0, 0, 0)
    minimum = sum(r.minimum for r in ranges)
    maximum = sum(r.maximum for r in ranges)
    expected = sum(r.expected for r in ranges)
    confidences = [r.confidence for r in ranges]
    if "low" in confidences:
        confidence = "low"
    elif "medium" in confidences:
        confidence = "medium"
    else:
        confidence = "high"
    assumptions = [a for r in ranges for a in r.assumptions]
    limitations = [l for r in ranges for l in r.limitations]
    completeness = sum(r.data_completeness for r in ranges) / max(1, len(ranges))
    return EstimateRange(
        minimum=minimum,
        maximum=maximum,
        expected=expected,
        confidence=confidence,
        assumptions=assumptions,
        limitations=limitations,
        data_completeness=min(1.0, completeness),
        requires_farmer_confirmation=any(r.requires_farmer_confirmation for r in ranges),
        requires_official_verification=any(r.requires_official_verification for r in ranges),
    )