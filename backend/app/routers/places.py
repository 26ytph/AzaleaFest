"""Places router (M3 owns). Mounted at /places by main.py.

Endpoints to implement (spec M0.4):
    GET    ""           -> Place[]
    POST   ""           -> Place
    DELETE "/{id}"      -> 204
"""
from fastapi import APIRouter

router = APIRouter()
