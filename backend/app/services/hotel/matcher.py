"""M4 匹配介面 — M3 import 的唯一入口 (spec M4.2)."""
from dataclasses import dataclass, field


@dataclass
class MatchResult:
    status: str                     # 'legal' | 'illegal' | 'unknown'
    match: dict | None              # matched hotel record
    alternatives: list = field(default_factory=list)
    score: float = 0.0


SCORE_THRESHOLD = 75


async def match_hotel(name: str, lat: float, lng: float) -> MatchResult:
    """旅館合法性比對。實作見 spec M4.2。"""
    raise NotImplementedError
