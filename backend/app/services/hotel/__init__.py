"""M4 hotel service — public surface for cross-module imports.

M3 imports `match_hotel` from this package. Keep the surface area minimal:
only `match_hotel` and `MatchResult` are intended for external consumers.
"""
from app.services.hotel.matcher import MatchResult, match_hotel

__all__ = ["MatchResult", "match_hotel"]
