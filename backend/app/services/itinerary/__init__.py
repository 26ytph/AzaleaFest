"""M7 itinerary service — public surface for cross-module imports.

Only `generate` is intended for external consumers (the router).
"""
from app.services.itinerary.generator import generate

__all__ = ["generate"]
