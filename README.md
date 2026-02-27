# PoP — Pick or Pass

Pick or Pass (PoP) is a Python web application that helps users decide whether a movie or book is worth their time. It combines Google Gemini AI for personalised evaluation, real-world ratings from TMDb and Google Books, streaming/purchase availability, and AI-powered similar-title recommendations — all in one view.

## Features

- User accounts with session-based authentication
- Multiple preference profiles per user (one active at a time)
- AI evaluation of any movie or book title using Google Gemini — returns a verdict (Yes / No / Maybe) with confidence score, reasoning, and potential concerns
- **Real-world ratings** — pulls audience scores and review snippets from TMDb (movies) and Google Books (books), cached for 24 hours
- **Where to watch / get** — streaming availability via TMDb's JustWatch-powered watch-providers endpoint for movies; Amazon and Google Play Books links for books
- **Clickable review links** — each review snippet links to its source page
- **AI recommendations** — after every evaluation, Gemini suggests 3 similar titles tailored to the user's preferences
- Decision history with filtering by type and verdict, and full pagination
- Session-persistent results — navigating away and back restores the last evaluation instantly
- Per-user rate limiting on API endpoints
- Health, readiness, and metrics endpoints
- Structured logging with optional JSON output
- Async AI evaluation with RQ + Redis and SQLite-backed response caching

## Technologies Used

- Flask (web framework)
- SQLAlchemy (ORM)
- Alembic (migrations)
- RQ + Redis (background jobs)
- Google Gemini AI via `google-genai` (evaluation + recommendations)
- TMDb API (movie ratings, review snippets, watch providers)
- Google Books API (book ratings, descriptions, purchase links)
- python-dotenv (environment variable management)

## Setup & Usage

### Prerequisites
- Python 3.x
- pip
- Redis (for async jobs; optional in dev)
- A free TMDb API key — sign up at [themoviedb.org](https://www.themoviedb.org/signup), then go to Settings → API
- A free Google Books API key — enable the Books API in [Google Cloud Console](https://console.cloud.google.com) and create a credential

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file with all required keys:
   ```env
   GEMINI_API_KEY=your_gemini_api_key
   TMDB_API_KEY=your_tmdb_api_key
   GOOGLE_BOOKS_API_KEY=your_google_books_api_key
   FLASK_SECRET_KEY=your_secret_key_here
   APP_ENV=development
   LOG_LEVEL=INFO
   LOG_FORMAT=text        # or json
   REDIS_URL=redis://localhost:6379/0
   ASYNC_ENABLED=true
   AI_TIMEOUT_SECONDS=15
   AI_RETRY_COUNT=2
   AI_RETRY_BACKOFF_SECONDS=0.5
   CACHE_TTL_SECONDS=86400
   ```

### Running the Application

1. Run migrations:
   ```bash
   alembic upgrade head
   ```

2. Start the app:
   ```bash
   python app.py
   ```

3. (Optional) Start a worker for async jobs:
   ```bash
   rq worker pop
   ```

   **macOS note:** if you see a crash related to `fork()` or the Objective-C runtime, use:
   ```bash
   rq worker pop --worker-class rq.worker.SimpleWorker
   ```

4. Open `http://localhost:5000` in your browser.

### Makefile helpers
```
make test
make worker
make worker-simple
```

## Project Structure

```
app.py               # Flask routes and application setup
ai_service.py        # Gemini API client, prompt builder, response parser
reviews.py           # TMDb + Google Books integration (ratings, snippets, watch providers)
recommendations.py   # Gemini-powered similar-title recommendations
jobs.py              # RQ background job handler
job_queue.py         # RQ queue factory
database.py          # SQLAlchemy models, session helpers, cache helpers
config.py            # Environment-based config classes
utils.py             # Preference normalisation and validation helpers
templates/
  base.html          # Shared layout, nav, global styles (Nunito font, light blue palette)
  index.html         # Home — search form, 3-column results grid, recommendations row
  history.html       # Decision history — filterable cards with shimmer loading
  preferences.html   # Preference editor
  login.html
  register.html
```

## Configuration

All configuration is driven by `APP_ENV` and `config.py`:

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development`, `staging`, or `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `LOG_FORMAT` | `text` | `text` or `json` |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rolling window for per-user rate limit |
| `RATE_LIMIT_MAX_REQUESTS` | `60` | Max requests per window |
| `ASYNC_ENABLED` | `true` | Enable RQ background evaluation |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `AI_TIMEOUT_SECONDS` | `15` | Per-attempt Gemini timeout |
| `AI_RETRY_COUNT` | `2` | Number of retries on failure |
| `AI_RETRY_BACKOFF_SECONDS` | `0.5` | Backoff multiplier between retries |
| `CACHE_TTL_SECONDS` | `86400` | SQLite cache TTL (reviews + AI responses) |

## API Endpoints

### Response Envelope
All API responses use a consistent envelope:
```json
{
  "success": true,
  "data": {},
  "error": null
}
```

### Auth
| Method | Path | Description |
|---|---|---|
| `POST` | `/users` | Register a new user |
| `POST` | `/login` | Log in (creates session) |
| `GET`  | `/logout` | Log out (clears session) |

### Protected Endpoints
All endpoints below require an active session.

| Method | Path | Description |
|---|---|---|
| `POST` | `/decide` | Evaluate a title — returns verdict, confidence, reasoning |
| `GET`  | `/jobs/<job_id>` | Poll async job status |
| `GET`  | `/reviews?title=&type=movie\|book` | Ratings, snippets, and watch providers |
| `GET`  | `/recommendations?title=&type=movie\|book` | 3 AI-generated similar-title recommendations |
| `GET`  | `/history` | Paginated decision history (supports `limit`, `offset`, `type`, `verdict`, `start`, `end` filters) |
| `GET`  | `/preferences` | Fetch active preferences |
| `POST` | `/preferences` | Save preferences |
| `DELETE` | `/preferences` | Delete active preferences |
| `GET`  | `/profiles` | List all preference profiles |
| `POST` | `/profiles` | Create a new profile |
| `POST` | `/profiles/<id>/activate` | Switch active profile |

### Health & Metrics
| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Liveness check |
| `GET` | `/readyz` | DB connectivity check |
| `GET` | `/metrics` | In-memory request counters |

## Rate Limiting

Per-user rolling window: 60 requests per minute by default. Configurable via `RATE_LIMIT_WINDOW_SECONDS` and `RATE_LIMIT_MAX_REQUESTS`.

## Caching

Review data (ratings, snippets, watch providers) is cached in the existing `ai_cache` SQLite table for 24 hours to avoid redundant API calls and stay within free-tier rate limits.

## License

Specify your license here (e.g., MIT).
