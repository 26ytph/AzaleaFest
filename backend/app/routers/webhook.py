"""Line webhook router (M3 owns). Mounted at /webhook by main.py.

Endpoints to implement (spec M3):
    POST "/line" -> Line bot webhook entry
"""
from fastapi import APIRouter

router = APIRouter()
