"""Hotels router (M4 owns). Mounted at /hotels by main.py.

Endpoint (spec M0.4 / M4.3):
    GET /hotels/verify?name=&lat=&lng=  -> HotelVerifyResult (M0.5)
"""
from fastapi import APIRouter

from app.services.hotel.matcher import match_hotel

router = APIRouter()


@router.get("/verify")
async def verify_hotel(name: str, lat: float, lng: float) -> dict:
    result = await match_hotel(name, lat, lng)

    match = None
    if result.match is not None:
        m = result.match
        match = {
            "id": m["id"],
            "name": m["name"],
            "address": m["address"],
            "lat": m.get("lat"),
            "lng": m.get("lng"),
        }
    alternatives = [
        {"id": a["id"], "name": a["name"], "address": a["address"]}
        for a in result.alternatives
    ]
    return {
        "status": result.status,
        "match": match,
        "alternatives": alternatives,
    }
