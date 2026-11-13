"""Filed readings and the code verdict passed into the model pipeline.

The verdict and the broken limits here are the values the limit check already
stored. Model steps read them and do not write them back.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ReportFacts:
    name: str
    station: str
    wind: Decimal
    temperature: Decimal
    fuel: Decimal
    note: str
    verdict: str
    broken_limits: tuple[str, ...]
    filed_at: datetime
