"""The arithmetic of time series: how many a metric creates, worked out on paper before querying anything."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import prod


@dataclass(frozen=True, slots=True)
class SeriesEstimate:
    """Series a counter and a histogram create for a set of label cardinalities."""

    label_combinations: int
    counter_series: int
    histogram_series: int

    @property
    def total(self) -> int:
        """Counter plus histogram series."""
        return self.counter_series + self.histogram_series


def expected_series(label_value_counts: Mapping[str, int], finite_buckets: int) -> SeriesEstimate:
    """Series for one counter and one histogram labeled by the given labels.

    Every distinct combination of label values is its own series. A histogram adds, per combination, one series per
    finite bucket, one for the ``+Inf`` bucket, one ``_sum`` and one ``_count``.
    """
    if finite_buckets < 0 or any(count < 0 for count in label_value_counts.values()):
        raise ValueError("counts must not be negative")
    combinations = prod(label_value_counts.values()) if label_value_counts else 1
    return SeriesEstimate(combinations, combinations, combinations * (finite_buckets + 1 + 2))
