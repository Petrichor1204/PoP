# PoP

Pick or Pass (PoP) is a Python web application that helps users decide whether a movie or book matches their personal preferences, using Google Gemini AI for evaluation.

## Features

- Collects user preferences for genres, pace, emotional tolerance, and goals
- Supports multiple preference profiles per user (one active at a time)
- Evaluates any user-provided movie or book title using Gemini AI
- Returns a verdict (Yes/No/Maybe) with confidence, reasoning, and potential mismatches
- Stores preferences and decision history in SQLite
- Simple UI for preferences, evaluation, and history

## Technologies Used

- Flask (web framework)
- SQLAlchemy (ORM)
- Alembic (migrations)
- Google Gemini AI (via google-genai)
- python-dotenv (for environment variable management)

## Project Structure

```
PoP/
├── app.py                # Main application logic
├── database.py           # DB models and data access
├── requirements.txt      # Python dependencies
├── migrations/           # Alembic migrations
├── templates/            # HTML templates
```

## How It Works

1. User saves preferences (likes, dislikes, pace, emotional tolerance, goal).
2. User submits a movie or book title for evaluation.
3. Gemini AI responds with a JSON verdict, confidence score, reasoning, and potential mismatches.
4. The app validates, stores, and displays the result.

### Example Output
```
Verdict: Yes (Confidence: 0.85)
Why:
You are likely to enjoy "Hustle" because it matches your preferences for fast-paced, motivational movies.

Potential concerns:
- None
```

## Setup & Usage

### Prerequisites
- Python 3.x
- pip

### Installation
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set up your Gemini API key in a `.env` file:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

### Running the Application
1. Start the app:
   ```bash
   python app.py
   ```
2. Open your browser and go to `http://localhost:5000`

## Migrations

Initialize the DB schema with Alembic:
```bash
alembic upgrade head
```

## API Endpoints

### Response Envelope
All API responses use:
```
{
  "success": true | false,
  "data": any | null,
  "error": { "message": string, "type": string } | null
}
```

### Users
- `POST /users`
  - Request body:
```
{
  "username": "alice",
  "email": "alice@example.com"
}
```
  - 201: `{success: true, data: {id, username, email}}`

### Preferences
- `GET /preferences` (uses `X-User-Id` header or `user_id` query param; defaults to `1`)
  - 200: `{success: true, data: preferences}`
  - 404: `{success: false, error: {message: "No saved preferences", type: "not_found"}}`
- `POST /preferences`
  - Request body:
```
{
  "likes": "action, adventure",
  "dislikes": "slow",
  "pace": "fast",
  "emotional_tolerance": "light",
  "goal": "escape",
  "profile_name": "default"
}
```
  - 200: `{success: true, data: {message: "Preferences updated successfully!"}}`
- `DELETE /preferences`
  - 200: `{success: true, data: {message: "Preferences deleted"}}`

### Profiles
- `GET /profiles` (by user)
- `POST /profiles` (creates profile and activates it)
- `POST /profiles/<id>/activate`

### Decisions
- `POST /decide`
  - Request body:
```
{
  "item_name": "Dune",
  "item_type": "movie"
}
```
  - 201: `{success: true, data: decision}`
  - 400: invalid input or ambiguous title (`error.type` may be `suggestions`)

### History (pagination + filters)
- `GET /history?limit=10&offset=0&type=movie&verdict=Yes&start=2026-01-01T00:00:00&end=2026-02-01T00:00:00`
  - 200: `{success: true, data: {items: [...], pagination: {limit, offset, total}}}`

## License
Specify your license here (e.g., MIT).
