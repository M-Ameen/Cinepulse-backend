# 🚀 CinePulse Vercel Backend

Production-ready Serverless REST API built with **FastAPI** and **MongoDB Atlas** for Vercel deployment.

---

## 🛠️ Step 1: Migrate SQLite Data to MongoDB Atlas

Run the migration script from the root folder:

```powershell
python migrate_to_atlas.py "YOUR_MONGODB_ATLAS_CONNECTION_STRING"
```

This will automatically:
1. Connect to your MongoDB Atlas cluster.
2. Read all 9,994 movies & series from `movies.db`.
3. Bulk upsert them into the `cinepulse.movies` collection.
4. Create full-text search and sorting indexes on `subjectId`, `title`, `ratingNum`, and `genre`.

---

## 🌐 Step 2: Deploy to Vercel

### Method A: Via GitHub (Recommended)
1. Initialize git and push this `backend/` folder to a GitHub repository:
   ```bash
   cd backend
   git init
   git add .
   git commit -m "Initial CinePulse Vercel backend"
   git remote add origin https://github.com/<your-username>/cinepulse-backend.git
   git push -u origin main
   ```
2. Go to [vercel.com/new](https://vercel.com/new) and click **Import** on your `cinepulse-backend` repository.
3. In **Environment Variables**, add:
   * **Key:** `MONGODB_URI`
   * **Value:** `mongodb+srv://<username>:<password>@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority`
4. Click **Deploy**. Vercel will give you a live production URL (e.g. `https://cinepulse-api.vercel.app`).

---

## 📱 Step 3: Connect Android App

Open `MovieApp/app/src/main/java/com/example/movie/data/api/ApiClient.kt` and update:

```kotlin
private const val BASE_URL = "https://your-project.vercel.app/api/"
```
