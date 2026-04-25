"""Itinerary router (M7 owns). Mounted at /itinerary by main.py.

Endpoints to implement (spec M0.4):
    POST "/generate" -> Itinerary
"""
from fastapi import APIRouter

router = APIRouter()
