"""
CinePulse — Production Vercel Serverless REST API
FastAPI + MongoDB Atlas backend for CinePulse Android App.
"""

import os
from typing import Optional
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, DESCENDING, ASCENDING
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="CinePulse API",
    description="High-performance streaming backend powered by Vercel & MongoDB Atlas",
    version="1.0.0",
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

# MongoDB Connection Singleton
_mongo_client: Optional[MongoClient] = None

def get_collection():
    global _mongo_client
    mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        raise HTTPException(
            status_code=500,
            detail="MONGODB_URI environment variable is not configured in Vercel."
        )
    if _mongo_client is None:
        _mongo_client = MongoClient(
            mongo_uri,
            maxPoolSize=20,
            minPoolSize=1,
            serverSelectionTimeoutMS=5000
        )
    db = _mongo_client[os.environ.get("MONGODB_DB", "cinepulse")]
    return db["movies"]

@app.get("/")
@app.get("/api")
@app.get("/health")
@app.get("/api/health")
def health():
    try:
        col = get_collection()
        count = col.estimated_document_count()
        return {
            "status": "healthy",
            "service": "CinePulse Vercel API",
            "database": "MongoDB Atlas",
            "total_titles": count
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

@app.get("/genres")
@app.get("/api/genres")
def get_genres():
    try:
        col = get_collection()
        raw_genres = col.distinct("genre")
        unique_genres = set()
        for g_str in raw_genres:
            if g_str:
                for part in g_str.split(","):
                    p = part.strip()
                    if p:
                        unique_genres.add(p)
        return {"code": 0, "genres": sorted(list(unique_genres))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/foryou")
@app.get("/api/foryou")
@app.get("/home")
@app.get("/api/home")
def get_home_feed(page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100)):
    try:
        col = get_collection()
        skip = (page - 1) * pageSize
        cursor = col.find({}, {"_id": 0}).sort("voteCountNum", DESCENDING).skip(skip).limit(pageSize)
        items = list(cursor)

        hero_banners = items[:5] if len(items) >= 5 else items
        trending_rail = items[5:15] if len(items) >= 15 else items

        sections = [
            {
                "type": "BANNER_CAROUSEL",
                "title": "Featured",
                "items": hero_banners
            },
            {
                "type": "CONTENT_RAIL",
                "title": "Trending Now",
                "items": trending_rail
            },
            {
                "type": "CONTENT_RAIL",
                "title": "All Titles",
                "items": items
            }
        ]

        return {
            "code": 0,
            "message": "success",
            "data": {
                "sections": sections,
                "items": items
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subjects")
@app.get("/api/subjects")
def get_subjects(
    page: int = Query(1, ge=1),
    perPage: int = Query(20, ge=1, le=100),
    genre: Optional[str] = None,
    subjectType: Optional[int] = None,
    sortBy: str = Query("votes", regex="^(votes|rating|release|title)$"),
    order: str = Query("desc", regex="^(asc|desc)$")
):
    try:
        col = get_collection()
        query = {}
        if genre:
            query["genre"] = {"$regex": genre, "$options": "i"}
        if subjectType:
            query["subjectType"] = subjectType

        sort_field = {
            "votes": "voteCountNum",
            "rating": "ratingNum",
            "release": "releaseDate",
            "title": "title"
        }.get(sortBy, "voteCountNum")

        direction = DESCENDING if order == "desc" else ASCENDING

        skip = (page - 1) * perPage
        total = col.count_documents(query)
        cursor = col.find(query, {"_id": 0}).sort(sort_field, direction).skip(skip).limit(perPage)
        items = list(cursor)

        total_pages = (total + perPage - 1) // perPage if total > 0 else 1

        return {
            "code": 0,
            "data": {
                "page": page,
                "perPage": perPage,
                "totalItems": total,
                "totalPages": total_pages,
                "hasNext": page < total_pages,
                "hasPrev": page > 1,
                "items": items
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
    search_term = q or keyword or ""
    try:
        col = get_collection()
        query = {}
        if search_term:
            query["title"] = {"$regex": search_term, "$options": "i"}
        if genre:
            query["genre"] = {"$regex": genre, "$options": "i"}
        if subjectType:
            query["subjectType"] = subjectType

        skip = (page - 1) * perPage
        total = col.count_documents(query)
        cursor = col.find(query, {"_id": 0}).sort("voteCountNum", DESCENDING).skip(skip).limit(perPage)
        items = list(cursor)

        total_pages = (total + perPage - 1) // perPage if total > 0 else 1

        return {
            "code": 0,
            "data": {
                "page": page,
                "perPage": perPage,
                "totalItems": total,
                "totalPages": total_pages,
                "items": items
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subjects/{subject_id}")
@app.get("/api/subjects/{subject_id}")
@app.get("/details")
@app.get("/api/details")
def get_subject_detail(subject_id: Optional[str] = None, id: Optional[str] = None):
    sid = subject_id or id
    if not sid:
        raise HTTPException(status_code=400, detail="Subject ID is required")
    try:
        col = get_collection()
        item = col.find_one({"subjectId": str(sid)}, {"_id": 0})
        if not item:
            raise HTTPException(status_code=404, detail="Subject not found")
        return {
            "code": 0,
            "data": item
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
