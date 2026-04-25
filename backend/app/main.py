"""FastAPI app entrypoint (spec M0.1, M0.4).

Mounts each module's router at the path prefix declared in spec M0.4.
Module owners add endpoints to their respective router file; main.py
itself should not need to change as modules fill in.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import hotels, itinerary, places, recommend, webhook

app = FastAPI(title="Taipei WanderGuard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(places.router, prefix="/places", tags=["places"])
app.include_router(hotels.router, prefix="/hotels", tags=["hotels"])
app.include_router(recommend.router, prefix="/recommend", tags=["recommend"])
app.include_router(itinerary.router, prefix="/itinerary", tags=["itinerary"])
app.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
