# 🚀 CinePulse Vercel & Local Backend

Production-ready High-Performance Serverless REST API built with **FastAPI** for **Vercel** and **MongoDB Atlas**, featuring automatic local **SQLite fallback** for zero-configuration offline development.

Optimized for **116,621+ movies and TV titles** with sub-20ms search and 65% bandwidth savings.

---

## ⚡ Core Features

- **Dual-Engine Data Access:**
  - **Production (Vercel):** Connects to MongoDB Atlas cluster (`cinepulse.movies`) using connection pooling and `$text` full-text search.
  - **Local Development:** Automatically falls back to the local `movies.db` (116k titles) with SQLite FTS5 if `MONGODB_URI` is not configured.
- **Card Projections:** List feeds (`/api/foryou`, `/api/subjects`, `/api/search`) strip heavy raw JSON and metadata, reducing payload size by ~65.3%.
- **Multi-Rail Curated Home Feed (`/api/foryou`):**
  - Hero Carousel (`BANNER_CAROUSEL`): Featured Blockbusters (2024–2026, $\ge 6.5$ rating)
  - Trending Now (`CONTENT_RAIL`)
  - Popular TV Series (`CONTENT_RAIL`)
  - Action & Adventure (`CONTENT_RAIL`)
  - Sci-Fi & Cyberpunk (`CONTENT_RAIL`)
  - Animation & Anime (`CONTENT_RAIL`)
  - Critically Acclaimed 8.0+ (`CONTENT_RAIL`)
- **In-Memory Caching:** 1-hour TTL for distinct genres, 15-minute TTL for curated home feed rails.
- **Contextual Recommendations (`/api/subjects/{id}/related`):** Hybrid resolution querying live editorial recommendations first, with automatic database genre/type similarity fallback.
- **Android Ready:** 100% compliant with Jetpack Compose CinePulse Android app DTO models (`ForYouResponse`, `SubjectsResponse`, `SubjectDetailResponse`).

---

## 📡 REST API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Health check & catalog count (116,621 titles) |
| `GET` | `/api/genres` | Distinct sorted genres (Cached, <10ms) |
| `GET` | `/api/foryou` | 7 Curated Netflix-style home rails (Cached, 15-min TTL) |
| `GET` | `/api/subjects` | Paginated catalog (`genre`, `subjectType`, `sortBy`, `order`) |
| `GET` | `/api/search` | Fast full-text search (`keyword`, `genre`, `subjectType`) |
| `GET` | `/api/subjects/{id}` | Full item details (stills, trailer, metadata) |
| `GET` | `/api/subjects/{id}/related` | Contextual recommendations ("More Like This") |

---

## 🏃 Running Locally

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start Uvicorn server (port 8080)
python -m uvicorn api.index:app --reload --port 8080
```

Verify in your browser or curl:
- `http://localhost:8080/api/health`
- `http://localhost:8080/api/foryou`
- `http://localhost:8080/docs` (Interactive OpenAPI Swagger UI)

---

## 🌐 Deploying to Vercel

### Method A: Via GitHub (Recommended)
1. Initialize git and push this `backend/` folder to a GitHub repository:
   ```bash
   cd backend
   git init
   git add .
   git commit -m "CinePulse Vercel API v1.2.0"
   git remote add origin https://github.com/<your-username>/cinepulse-backend.git
   git push -u origin main
   ```
2. Go to [vercel.com/new](https://vercel.com/new) and click **Import** on your `cinepulse-backend` repository.
3. In **Environment Variables**, configure:
   * `MONGODB_URI`: `mongodb+srv://<username>:<password>@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority`
   * `MONGODB_DB`: `cinepulse`
4. Click **Deploy**. Vercel will assign a production URL (e.g. `https://cinepulse-backend.vercel.app`).

---

## 📱 Android Client Configuration

In `d:\MoviesData\MovieApp\app\src\main\java\com\example\movie\data\api\ApiClient.kt`:

- For **Local Emulator Testing**:
  ```kotlin
  private const val LIVE_BASE_URL = "http://10.0.2.2:8080/api/"
  ```
- For **Production Vercel Cloud**:
  ```kotlin
  private const val LIVE_BASE_URL = "https://cinepulse-backend.vercel.app/api/"
  ```
