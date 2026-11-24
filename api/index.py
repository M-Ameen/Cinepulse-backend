"""
CinePulse — Production Vercel Serverless REST API
FastAPI + MongoDB Atlas backend with automatic local SQLite fallback.
Optimized for 116,621+ movies and TV titles.
"""

import os
import re
import time
import json
import sqlite3
import hashlib
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Tuple
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, DESCENDING, ASCENDING
from dotenv import load_dotenv

# Load .env from backend directory or project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))
load_dotenv()

app = FastAPI(
    title="CinePulse API",
    description="High-performance streaming backend powered by MongoDB Atlas & Vercel (116k+ catalog)",
    version="1.2.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

# Enable CORS for Android client, Web clients & API testing tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Projections & Constants
# ---------------------------------------------------------
CARD_PROJECTION_KEYS = [
    "subjectId",
    "title",
    "description",
    "cover",
    "stills",
    "imdbRatingValue",
    "imdbRatingCount",
    "ratingNum",
    "voteCountNum",
    "releaseDate",
    "duration",
    "genre",
    "subjectType",
    "type",
    "countryName",
    "detailPath",
    "corner"
]

CARD_PROJECTION = {k: 1 for k in CARD_PROJECTION_KEYS}
CARD_PROJECTION["_id"] = 0

def format_card_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures consistent numeric sorting fields and strips heavy metadata."""
    res = {}
    for k in CARD_PROJECTION_KEYS:
        if k in doc:
            res[k] = doc[k]

    # Ensure subjectId is a string
    if "subjectId" in res:
        res["subjectId"] = str(res["subjectId"])

    # Ensure ratingNum
    if "ratingNum" not in res:
        try:
            res["ratingNum"] = float(res.get("imdbRatingValue", 0) or 0)
        except (ValueError, TypeError):
            res["ratingNum"] = 0.0

    # Ensure voteCountNum
    if "voteCountNum" not in res:
        try:
            res["voteCountNum"] = int(res.get("imdbRatingCount", 0) or 0)
        except (ValueError, TypeError):
            res["voteCountNum"] = 0

    return res

# In-Memory Cache Structures
_genres_cache: Dict[str, Any] = {"timestamp": 0, "data": []}
GENRES_CACHE_TTL = 3600  # 1 hour

_home_cache: Dict[str, Any] = {"timestamp": 0, "data": None}
HOME_CACHE_TTL = 900     # 15 minutes

# ---------------------------------------------------------
# Dual Storage Engine (Atlas Primary + SQLite Fallback)
# ---------------------------------------------------------
_mongo_client: Optional[MongoClient] = None
_sqlite_path: Optional[str] = None
_storage_engine: Optional[str] = None  # "mongo" or "sqlite"

def find_sqlite_db() -> Optional[str]:
    possible_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "movies.db"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "movies.db"),
        r"d:\MoviesData\movies.db",
        "movies.db"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p
    return None

def get_engine() -> Tuple[str, Any]:
    """Returns active storage engine ('mongo', collection) or ('sqlite', db_path)."""
    global _mongo_client, _sqlite_path, _storage_engine

    # 1. Try MongoDB Atlas if URI is configured
    mongo_uri = os.environ.get("MONGODB_URI")
    if mongo_uri:
        try:
            if _mongo_client is None:
                _mongo_client = MongoClient(
                    mongo_uri,
                    maxPoolSize=50,
                    minPoolSize=2,
                    serverSelectionTimeoutMS=4000
                )
                # Verify connection
                _mongo_client.admin.command("ping")
            db = _mongo_client[os.environ.get("MONGODB_DB", "cinepulse")]
            _storage_engine = "mongo"
            return "mongo", db["movies"]
        except Exception:
            _mongo_client = None

    # 2. Fall back to local SQLite database (116k catalog)
    if _sqlite_path is None:
        _sqlite_path = find_sqlite_db()

    if _sqlite_path and os.path.exists(_sqlite_path):
        _storage_engine = "sqlite"
        return "sqlite", _sqlite_path

    raise HTTPException(
        status_code=503,
        detail="No database available. Neither MongoDB Atlas nor local movies.db found."
    )

def get_sqlite_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------------------------------------------
# Helper: Live Gateway Client Token
# ---------------------------------------------------------
def _get_live_client_token() -> str:
    ts = str(int(time.time()))
    token_hash = hashlib.md5(ts[::-1].encode()).hexdigest()
    return f"{ts},{token_hash}"

# ---------------------------------------------------------
# Health & Status Endpoint
# ---------------------------------------------------------
@app.get("/")
@app.get("/api")
@app.get("/health")
@app.get("/api/health")
def health():
    try:
        engine, handle = get_engine()
        if engine == "mongo":
            count = handle.estimated_document_count()
            db_label = "MongoDB Atlas"
        else:
            with get_sqlite_conn(handle) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM subjects")
                count = cur.fetchone()[0]
            db_label = f"SQLite Local Catalog ({os.path.basename(handle)})"

        return {
            "status": "healthy",
            "service": "CinePulse Vercel API",
            "engine": db_label,
            "total_titles": count,
            "version": "1.2.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

# ---------------------------------------------------------
# Cached Genres Endpoint (Sub-1ms response)
# ---------------------------------------------------------
@app.get("/genres")
@app.get("/api/genres")
def get_genres():
    global _genres_cache
    now = time.time()
    if _genres_cache["data"] and (now - _genres_cache["timestamp"]) < GENRES_CACHE_TTL:
        return {
            "code": 0,
            "message": "success",
            "genres": _genres_cache["data"]
        }

    try:
        engine, handle = get_engine()
        unique_genres = set()

        if engine == "mongo":
            raw_genres = handle.distinct("genre")
            for g_str in raw_genres:
                if g_str:
                    for part in str(g_str).split(","):
                        p = part.strip()
                        if p and len(p) < 30:
                            unique_genres.add(p)
        else:
            with get_sqlite_conn(handle) as conn:
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT genre FROM subjects WHERE genre IS NOT NULL AND genre != ''")
                for row in cur.fetchall():
                    for part in str(row["genre"]).split(","):
                        p = part.strip()
                        if p and len(p) < 30:
                            unique_genres.add(p)

        sorted_genres = sorted(list(unique_genres))
        _genres_cache = {"timestamp": now, "data": sorted_genres}
        return {
            "code": 0,
            "message": "success",
            "genres": sorted_genres
        }
    except Exception as e:
        if _genres_cache["data"]:
            return {
                "code": 0,
                "message": "success",
                "genres": _genres_cache["data"]
            }
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Multi-Rail Curated Home Feed (Netflix-Style)
# ---------------------------------------------------------
@app.get("/foryou")
@app.get("/api/foryou")
@app.get("/home")
@app.get("/api/home")
def get_home_feed(page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100)):
    global _home_cache
    now = time.time()

    # Serve cached home structure for page 1 if fresh
    if page == 1 and _home_cache["data"] and (now - _home_cache["timestamp"]) < HOME_CACHE_TTL:
        cached_data = _home_cache["data"]
        return {
            "code": 0,
            "message": "success",
            "sections": cached_data.get("sections", []),
            "items": cached_data.get("items", []),
            "data": cached_data
        }

    try:
        engine, handle = get_engine()

        if page == 1:
            if engine == "mongo":
                col = handle
                # 1. Hero Carousel: High rating & recent releases (2024-2026) with backdrops
                hero_banners = list(col.find(
                    {"releaseDate": {"$gte": "2024-01-01"}, "ratingNum": {"$gte": 6.5}},
                    CARD_PROJECTION
                ).sort("voteCountNum", DESCENDING).limit(6))

                if len(hero_banners) < 4:
                    hero_banners = list(col.find({}, CARD_PROJECTION).sort("voteCountNum", DESCENDING).limit(6))

                # 2. Trending Now: Top overall by popularity
                trending_rail = list(col.find({}, CARD_PROJECTION).sort("voteCountNum", DESCENDING).limit(15))

                # 3. Popular TV Series: Top series only (subjectType == 2)
                series_rail = list(col.find(
                    {"subjectType": 2},
                    CARD_PROJECTION
                ).sort("voteCountNum", DESCENDING).limit(15))

                # 4. Action Blockbusters
                action_rail = list(col.find(
                    {"genre": {"$regex": "Action", "$options": "i"}},
                    CARD_PROJECTION
                ).sort("voteCountNum", DESCENDING).limit(15))

                # 5. Sci-Fi & Cyberpunk
                scifi_rail = list(col.find(
                    {"genre": {"$regex": "Sci-Fi", "$options": "i"}},
                    CARD_PROJECTION
                ).sort("voteCountNum", DESCENDING).limit(15))

                # 6. Anime & Animation
                animation_rail = list(col.find(
                    {"genre": {"$regex": "Animation", "$options": "i"}},
                    CARD_PROJECTION
                ).sort("voteCountNum", DESCENDING).limit(15))

                # 7. Critically Acclaimed: 8.0+ Rating
                top_rated_rail = list(col.find(
                    {"ratingNum": {"$gte": 8.0}, "voteCountNum": {"$gte": 500}},
                    CARD_PROJECTION
                ).sort([("ratingNum", DESCENDING), ("voteCountNum", DESCENDING)]).limit(15))

            else:
                # SQLite Fast Index-Backed Queries
                with get_sqlite_conn(handle) as conn:
                    cur = conn.cursor()

                    def query_cards(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
                        cur.execute(sql, params)
                        return [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]

                    hero_banners = query_cards(
                        "SELECT raw_json FROM subjects WHERE release_date >= '2024-01-01' AND imdb_rating >= 6.5 ORDER BY imdb_vote_count DESC LIMIT 6"
                    )
                    if len(hero_banners) < 4:
                        hero_banners = query_cards(
                            "SELECT raw_json FROM subjects ORDER BY imdb_vote_count DESC LIMIT 6"
                        )

                    trending_rail = query_cards(
                        "SELECT raw_json FROM subjects ORDER BY imdb_vote_count DESC LIMIT 15"
                    )

                    series_rail = query_cards(
                        "SELECT raw_json FROM subjects WHERE subject_type = 2 ORDER BY imdb_vote_count DESC LIMIT 15"
                    )

                    action_rail = query_cards(
                        "SELECT raw_json FROM subjects WHERE genre LIKE '%Action%' ORDER BY imdb_vote_count DESC LIMIT 15"
                    )

                    scifi_rail = query_cards(
                        "SELECT raw_json FROM subjects WHERE genre LIKE '%Sci-Fi%' ORDER BY imdb_vote_count DESC LIMIT 15"
                    )

                    animation_rail = query_cards(
                        "SELECT raw_json FROM subjects WHERE genre LIKE '%Animation%' ORDER BY imdb_vote_count DESC LIMIT 15"
                    )

                    top_rated_rail = query_cards(
                        "SELECT raw_json FROM subjects WHERE imdb_rating >= 8.0 AND imdb_vote_count >= 500 ORDER BY imdb_rating DESC, imdb_vote_count DESC LIMIT 15"
                    )

            sections = [
                {
                    "type": "BANNER_CAROUSEL",
                    "title": "Featured Blockbusters",
                    "items": hero_banners
                },
                {
                    "type": "CONTENT_RAIL",
                    "title": "Trending Now",
                    "items": trending_rail
                },
                {
                    "type": "CONTENT_RAIL",
                    "title": "Popular TV Series",
                    "items": series_rail
                },
                {
                    "type": "CONTENT_RAIL",
                    "title": "Action & Adventure",
                    "items": action_rail
                },
                {
                    "type": "CONTENT_RAIL",
                    "title": "Sci-Fi & Cyberpunk",
                    "items": scifi_rail
                },
                {
                    "type": "CONTENT_RAIL",
                    "title": "Animation & Anime",
                    "items": animation_rail
                },
                {
                    "type": "CONTENT_RAIL",
                    "title": "Critically Acclaimed (8.0+)",
                    "items": top_rated_rail
                }
            ]

            response_data = {
                "sections": sections,
                "items": trending_rail
            }

            _home_cache = {"timestamp": now, "data": response_data}

            return {
                "code": 0,
                "message": "success",
                "sections": sections,
                "items": trending_rail,
                "data": response_data
            }
        else:
            # Subsequent pages paginate through general catalog
            skip = (page - 1) * pageSize
            if engine == "mongo":
                col = handle
                cursor = col.find({}, CARD_PROJECTION).sort("voteCountNum", DESCENDING).skip(skip).limit(pageSize)
                items = list(cursor)
            else:
                with get_sqlite_conn(handle) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT raw_json FROM subjects ORDER BY imdb_vote_count DESC LIMIT ? OFFSET ?",
                        (pageSize, skip)
                    )
                    items = [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]

            page_section = [{
                "type": "CONTENT_RAIL",
                "title": f"Discover (Page {page})",
                "items": items
            }]

            return {
                "code": 0,
                "message": "success",
                "sections": page_section,
                "items": items,
                "data": {
                    "sections": page_section,
                    "items": items
                }
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Paginated Catalog Filtering
# ---------------------------------------------------------
@app.get("/subjects")
@app.get("/api/subjects")
def get_subjects(
    page: int = Query(1, ge=1),
    perPage: int = Query(20, ge=1, le=100),
    genre: Optional[str] = None,
    subjectType: Optional[int] = None,
    sortBy: str = Query("votes", pattern="^(votes|rating|release|title)$"),
    order: str = Query("desc", pattern="^(asc|desc)$")
):
    try:
        engine, handle = get_engine()
        skip = (page - 1) * perPage

        if engine == "mongo":
            col = handle
            query: Dict[str, Any] = {}
            if genre:
                query["genre"] = {"$regex": re.escape(genre), "$options": "i"}
            if subjectType:
                query["subjectType"] = subjectType

            sort_field = {
                "votes": "voteCountNum",
                "rating": "ratingNum",
                "release": "releaseDate",
                "title": "title"
            }.get(sortBy, "voteCountNum")

            direction = DESCENDING if order == "desc" else ASCENDING

            # Fast count estimation when query is empty
            if not query:
                total = col.estimated_document_count()
            else:
                total = col.count_documents(query)

            cursor = col.find(query, CARD_PROJECTION).sort(sort_field, direction).skip(skip).limit(perPage)
            items = list(cursor)
        else:
            with get_sqlite_conn(handle) as conn:
                cur = conn.cursor()
                where_clauses = []
                params = []

                if genre:
                    where_clauses.append("genre LIKE ?")
                    params.append(f"%{genre}%")
                if subjectType:
                    where_clauses.append("subject_type = ?")
                    params.append(subjectType)

                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

                if not where_clauses:
                    cur.execute("SELECT COUNT(*) FROM subjects")
                    total = cur.fetchone()[0]
                else:
                    cur.execute(f"SELECT COUNT(*) FROM subjects {where_sql}", params)
                    total = cur.fetchone()[0]

                sort_col = {
                    "votes": "imdb_vote_count",
                    "rating": "imdb_rating",
                    "release": "release_date",
                    "title": "title"
                }.get(sortBy, "imdb_vote_count")

                direction_sql = "DESC" if order == "desc" else "ASC"
                query_sql = f"SELECT raw_json FROM subjects {where_sql} ORDER BY {sort_col} {direction_sql} LIMIT ? OFFSET ?"
                cur.execute(query_sql, params + [perPage, skip])
                items = [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]

        total_pages = (total + perPage - 1) // perPage if total > 0 else 1

        data_obj = {
            "page": page,
            "perPage": perPage,
            "totalItems": total,
            "totalPages": total_pages,
            "hasNext": page < total_pages,
            "hasPrev": page > 1,
            "items": items
        }

        return {
            "code": 0,
            "message": "success",
            "items": items,
            "data": data_obj
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# High-Performance Search (Atlas $text / SQLite FTS5)
# ---------------------------------------------------------
@app.get("/subjects/search")
@app.get("/api/subjects/search")
@app.get("/search")
@app.get("/api/search")
def search_subjects(
    q: Optional[str] = None,
    keyword: Optional[str] = None,
    genre: Optional[str] = None,
    subjectType: Optional[int] = None,
    page: int = Query(1, ge=1),
    perPage: int = Query(20, ge=1, le=100)
):
    search_term = (q or keyword or "").strip()
    try:
        engine, handle = get_engine()
        skip = (page - 1) * perPage
        items: List[Dict[str, Any]] = []
        total = 0

        if engine == "mongo":
            col = handle
            if search_term:
                # 1. Fast Atlas Text Search ($text)
                text_query: Dict[str, Any] = {"$text": {"$search": search_term}}
                if genre:
                    text_query["genre"] = {"$regex": re.escape(genre), "$options": "i"}
                if subjectType:
                    text_query["subjectType"] = subjectType

                try:
                    text_cursor = col.find(
                        text_query,
                        {**CARD_PROJECTION, "score": {"$meta": "textScore"}}
                    ).sort([
                        ("score", {"$meta": "textScore"}),
                        ("voteCountNum", DESCENDING)
                    ]).skip(skip).limit(perPage)

                    items = list(text_cursor)
                    if items:
                        total = col.count_documents(text_query)
                except Exception:
                    items = []

                # 2. Fallback: Prefix regex search if $text yielded 0 results
                if not items:
                    clean_term = re.escape(search_term)
                    regex_query: Dict[str, Any] = {
                        "$or": [
                            {"title": {"$regex": f"^{clean_term}", "$options": "i"}},
                            {"title": {"$regex": clean_term, "$options": "i"}}
                        ]
                    }
                    if genre:
                        regex_query["genre"] = {"$regex": re.escape(genre), "$options": "i"}
                    if subjectType:
                        regex_query["subjectType"] = subjectType

                    total = col.count_documents(regex_query)
                    cursor = col.find(regex_query, CARD_PROJECTION).sort("voteCountNum", DESCENDING).skip(skip).limit(perPage)
                    items = list(cursor)

            else:
                browse_query: Dict[str, Any] = {}
                if genre:
                    browse_query["genre"] = {"$regex": re.escape(genre), "$options": "i"}
                if subjectType:
                    browse_query["subjectType"] = subjectType

                total = col.count_documents(browse_query) if browse_query else col.estimated_document_count()
                cursor = col.find(browse_query, CARD_PROJECTION).sort("voteCountNum", DESCENDING).skip(skip).limit(perPage)
                items = list(cursor)

            for it in items:
                it.pop("score", None)

        else:
            # SQLite Engine: FTS5 with prefix fallback
            with get_sqlite_conn(handle) as conn:
                cur = conn.cursor()

                if search_term:
                    # Clean search term for FTS5 syntax
                    sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', search_term).strip()
                    words = [w for w in sanitized.split() if w]
                    fts_query = " ".join([f'"{w}"*' for w in words]) if words else ""

                    if fts_query:
                        try:
                            count_sql = "SELECT COUNT(*) FROM subjects s JOIN subjects_fts f ON s.subject_id = f.subject_id WHERE f.title MATCH ?"
                            cur.execute(count_sql, (fts_query,))
                            total = cur.fetchone()[0]

                            if total > 0:
                                search_sql = """
                                    SELECT s.raw_json FROM subjects s
                                    JOIN subjects_fts f ON s.subject_id = f.subject_id
                                    WHERE f.title MATCH ?
                                    ORDER BY s.imdb_vote_count DESC
                                    LIMIT ? OFFSET ?
                                """
                                cur.execute(search_sql, (fts_query, perPage, skip))
                                items = [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]
                        except Exception:
                            items = []

                    # Fallback if FTS yielded 0 results
                    if not items:
                        # Fast indexed prefix search (sub-2ms using idx_subjects_title)
                        prefix_param = f"{search_term}%"
                        cur.execute("SELECT COUNT(*) FROM subjects WHERE title LIKE ?", (prefix_param,))
                        total = cur.fetchone()[0]

                        if total > 0:
                            cur.execute(
                                "SELECT raw_json FROM subjects WHERE title LIKE ? ORDER BY imdb_vote_count DESC LIMIT ? OFFSET ?",
                                (prefix_param, perPage, skip)
                            )
                            items = [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]

                else:
                    where_clauses = []
                    params = []
                    if genre:
                        where_clauses.append("genre LIKE ?")
                        params.append(f"%{genre}%")
                    if subjectType:
                        where_clauses.append("subject_type = ?")
                        params.append(subjectType)

                    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                    if not where_clauses:
                        cur.execute("SELECT COUNT(*) FROM subjects")
                        total = cur.fetchone()[0]
                    else:
                        cur.execute(f"SELECT COUNT(*) FROM subjects {where_sql}", params)
                        total = cur.fetchone()[0]

                    cur.execute(
                        f"SELECT raw_json FROM subjects {where_sql} ORDER BY imdb_vote_count DESC LIMIT ? OFFSET ?",
                        params + [perPage, skip]
                    )
                    items = [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]

        total_pages = (total + perPage - 1) // perPage if total > 0 else 1

        data_obj = {
            "page": page,
            "perPage": perPage,
            "totalItems": total,
            "totalPages": total_pages,
            "hasNext": page < total_pages,
            "hasPrev": page > 1,
            "items": items
        }

        return {
            "code": 0,
            "message": "success",
            "items": items,
            "data": data_obj
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Single Subject Detail (Full Document Metadata)
# ---------------------------------------------------------
@app.get("/subjects/{subject_id}")
@app.get("/api/subjects/{subject_id}")
@app.get("/details")
@app.get("/api/details")
def get_subject_detail(subject_id: Optional[str] = None, id: Optional[str] = None):
    sid = subject_id or id
    if not sid:
        raise HTTPException(status_code=400, detail="Subject ID is required")
    try:
        engine, handle = get_engine()
        item = None

        if engine == "mongo":
            item = handle.find_one({"subjectId": str(sid)}, {"_id": 0, "raw_json": 0})
        else:
            with get_sqlite_conn(handle) as conn:
                cur = conn.cursor()
                cur.execute("SELECT raw_json FROM subjects WHERE subject_id = ?", (str(sid),))
                row = cur.fetchone()
                if row:
                    item = json.loads(row["raw_json"])

        if not item:
            raise HTTPException(status_code=404, detail="Subject not found")

        # Strip internal fields if present
        item.pop("_id", None)
        item.pop("raw_json", None)

        return {
            "code": 0,
            "message": "success",
            "data": item
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Contextual Recommendations ("More Like This")
# ---------------------------------------------------------
@app.get("/subjects/{subject_id}/related")
@app.get("/api/subjects/{subject_id}/related")
@app.get("/subjects/{subject_id}/recommendations")
@app.get("/api/subjects/{subject_id}/recommendations")
def get_recommendations(subject_id: str, limit: int = Query(12, ge=1, le=30)):
    if not subject_id:
        raise HTTPException(status_code=400, detail="Subject ID is required")

    # 1. Primary: Try Live Gateway recommendations for authentic editorial matches
    try:
        token = _get_live_client_token()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://movieboxhd.net/",
            "Origin": "https://movieboxhd.net",
            "X-No-High-Risk-Restrict": "0",
            "X-Client-Token": token,
            "X-Request-Lang": "en",
            "X-Client-Info": '{"timezone":"UTC"}'
        }
        url = f"https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/detail-rec?subjectId={subject_id}&page=1&perPage={limit}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as resp:
            live_data = json.loads(resp.read().decode())
            live_items = live_data.get("data", {}).get("items", [])
            if live_items and len(live_items) > 0:
                formatted_live = [format_card_doc(it) for it in live_items[:limit]]
                return {
                    "code": 0,
                    "message": "success",
                    "items": formatted_live,
                    "data": {
                        "items": formatted_live,
                        "source": "live_editorial"
                    }
                }
    except Exception:
        pass  # Fall back to database similarity

    # 2. Fallback: Query Database for matching genre & subjectType
    try:
        engine, handle = get_engine()
        items: List[Dict[str, Any]] = []

        if engine == "mongo":
            col = handle
            target = col.find_one({"subjectId": str(subject_id)}, {"_id": 0, "genre": 1, "subjectType": 1, "title": 1})
            query: Dict[str, Any] = {"subjectId": {"$ne": str(subject_id)}}

            if target:
                if target.get("subjectType"):
                    query["subjectType"] = target["subjectType"]

                raw_genre = target.get("genre", "")
                if raw_genre:
                    primary_genre = [g.strip() for g in str(raw_genre).split(",") if g.strip()]
                    if primary_genre:
                        query["genre"] = {"$regex": re.escape(primary_genre[0]), "$options": "i"}

            cursor = col.find(query, CARD_PROJECTION).sort([("ratingNum", DESCENDING), ("voteCountNum", DESCENDING)]).limit(limit)
            items = list(cursor)
        else:
            with get_sqlite_conn(handle) as conn:
                cur = conn.cursor()
                cur.execute("SELECT genre, subject_type FROM subjects WHERE subject_id = ?", (str(subject_id),))
                target_row = cur.fetchone()

                where_clauses = ["subject_id != ?"]
                params = [str(subject_id)]

                if target_row:
                    st = target_row["subject_type"]
                    if st:
                        where_clauses.append("subject_type = ?")
                        params.append(st)

                    raw_genre = target_row["genre"]
                    if raw_genre:
                        parts = [p.strip() for p in raw_genre.split(",") if p.strip()]
                        if parts:
                            where_clauses.append("genre LIKE ?")
                            params.append(f"%{parts[0]}%")

                where_sql = "WHERE " + " AND ".join(where_clauses)
                sql = f"SELECT raw_json FROM subjects {where_sql} ORDER BY imdb_rating DESC, imdb_vote_count DESC LIMIT ?"
                cur.execute(sql, params + [limit])
                items = [format_card_doc(json.loads(r["raw_json"])) for r in cur.fetchall()]

        return {
            "code": 0,
            "message": "success",
            "items": items,
            "data": {
                "items": items,
                "source": "database_similarity"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Resilient Catch-All Route Dispatcher for Vercel
# ---------------------------------------------------------
@app.api_route("/{full_path:path}", methods=["GET", "POST", "HEAD"])
def catch_all_dispatcher(full_path: str, request: Request):
    """
    Guarantees requests on Vercel never 404 due to path prefix or rewrite differences.
    """
    raw_path = (request.url.path or full_path or "").lower()
    qp = request.query_params

    # 1. Health check & Root
    if "health" in raw_path or raw_path.strip("/") in ["", "api"]:
        return health()

    # 2. ForYou / Home Feed
    if "foryou" in raw_path or "home" in raw_path:
        page = int(qp.get("page", 1))
        pageSize = int(qp.get("pageSize", 20))
        return get_home_feed(page=page, pageSize=pageSize)

    # 3. Genres
    if "genres" in raw_path:
        return get_genres()

    # 4. Related / Recommendations
    if "related" in raw_path or "recommendations" in raw_path:
        parts = [p for p in raw_path.split("/") if p]
        sid = ""
        for i, p in enumerate(parts):
            if p in ["related", "recommendations"] and i > 0:
                sid = parts[i - 1]
                break
        if not sid:
            sid = qp.get("subjectId") or qp.get("id") or ""
        limit = int(qp.get("limit", 12))
        return get_recommendations(subject_id=sid, limit=limit)

    # 5. Search
    if "search" in raw_path:
        return search_subjects(
            q=qp.get("q"),
            keyword=qp.get("keyword"),
            genre=qp.get("genre"),
            subjectType=int(qp["subjectType"]) if qp.get("subjectType") else None,
            page=int(qp.get("page", 1)),
            perPage=int(qp.get("perPage", 20))
        )

    # 6. Single Subject Details
    if "details" in raw_path or ("subjects/" in raw_path and not raw_path.endswith("subjects")):
        parts = [p for p in raw_path.split("/") if p]
        sid = parts[-1] if parts else ""
        if sid == "details":
            sid = qp.get("id") or qp.get("subjectId") or ""
        return get_subject_detail(subject_id=sid)

    # 7. Subjects Catalog
    if "subjects" in raw_path:
        return get_subjects(
            page=int(qp.get("page", 1)),
            perPage=int(qp.get("perPage", 20)),
            genre=qp.get("genre"),
            subjectType=int(qp["subjectType"]) if qp.get("subjectType") else None,
            sortBy=qp.get("sortBy", "votes"),
            order=qp.get("order", "desc")
        )

    return {
        "code": 404,
        "detail": "Not Found",
        "debug": {
            "requested_path": raw_path,
            "full_path": full_path,
            "url": str(request.url)
        }
    }

