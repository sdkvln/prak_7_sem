"""Storage: CRUD для объявлений о продаже квартир поверх SQLite."""
import os
import sqlite3
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

config = yaml.safe_load(open(os.getenv("CONFIG_PATH", "config.yaml")))
DB_PATH = config["db_path"]

FIELDS = ["price", "date", "region", "building_type", "level", "levels",
          "rooms", "area", "kitchen_area", "object_type"]


class Listing(BaseModel):
    price: float
    date: str | None = None
    region: int
    building_type: int | None = None
    level: int | None = None
    levels: int | None = None
    rooms: int | None = None
    area: float
    kitchen_area: float | None = None
    object_type: int | None = None


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS listings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, price REAL, date TEXT, region INTEGER, "
            "building_type INTEGER, level INTEGER, levels INTEGER, rooms INTEGER, "
            "area REAL, kitchen_area REAL, object_type INTEGER)"
        )


app = FastAPI(title="Storage")
init_db()


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/listings", status_code=201)
def create_listing(item: Listing):
    with db() as conn:
        cur = conn.execute(
            f"INSERT INTO listings ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
            [getattr(item, f) for f in FIELDS],
        )
    return {"id": cur.lastrowid}


@app.post("/listings/bulk", status_code=201)
def create_many(items: list[Listing]):
    with db() as conn:
        conn.executemany(
            f"INSERT INTO listings ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
            [[getattr(item, f) for f in FIELDS] for item in items],
        )
    return {"inserted": len(items)}


@app.get("/listings")
def list_listings(limit: int = 100, offset: int = 0, region: int | None = None):
    query, params = "SELECT * FROM listings", []
    if region is not None:
        query += " WHERE region = ?"
        params.append(region)
    query += " ORDER BY id LIMIT ? OFFSET ?"
    with db() as conn:
        rows = conn.execute(query, params + [limit, offset]).fetchall()
    return [dict(r) for r in rows]


@app.get("/listings/count")
def count_listings():
    with db() as conn:
        return {"count": conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]}


@app.get("/listings/{listing_id}")
def get_listing(listing_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM listings WHERE id = ?", [listing_id]).fetchone()
    if row is None:
        raise HTTPException(404, f"объявление {listing_id} не найдено")
    return dict(row)


@app.put("/listings/{listing_id}")
def update_listing(listing_id: int, item: Listing):
    with db() as conn:
        cur = conn.execute(
            f"UPDATE listings SET {', '.join(f + ' = ?' for f in FIELDS)} WHERE id = ?",
            [getattr(item, f) for f in FIELDS] + [listing_id],
        )
    if cur.rowcount == 0:
        raise HTTPException(404, f"объявление {listing_id} не найдено")
    return {"id": listing_id}


@app.delete("/listings/{listing_id}")
def delete_listing(listing_id: int):
    with db() as conn:
        cur = conn.execute("DELETE FROM listings WHERE id = ?", [listing_id])
    if cur.rowcount == 0:
        raise HTTPException(404, f"объявление {listing_id} не найдено")
    return {"deleted": listing_id}


@app.delete("/listings")
def delete_all():
    with db() as conn:
        cur = conn.execute("DELETE FROM listings")
    return {"deleted": cur.rowcount}


if __name__ == "__main__":
    uvicorn.run(app, host=config["host"], port=config["port"])
