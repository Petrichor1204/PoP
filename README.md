
# PoP

Pick or Pass (PoP) is a Python web application that helps users decide whether a movie or book matches their personal preferences, using Google Gemini AI for evaluation.

## Features

- Collects user preferences for genres, pace, emotional tolerance, and goals via a web form
- Evaluates a hardcoded title ("Hustle") against user preferences using Gemini AI
- Returns a verdict (PICK, PASS, MAYBE) with confidence and reasoning
- Cleans and formats AI responses for user-friendly display
- No spoilers or unnecessary commentary in AI output

## Technologies Used

- Flask (web framework)
- Google Gemini AI (via google-genai)
- python-dotenv (for environment variable management)

## Project Structure

```
PoP/
├── app.py                # Main application logic
├── requirements.txt      # Python dependencies
├── static/               # Static assets (CSS, JS, images)
├── templates/
│   └── index.html        # Main HTML template
```

## How It Works

1. User fills out a form specifying likes, dislikes, preferred pace, emotional tolerance, and goal for consuming media.
2. On form submission, preferences are normalized and sent to Gemini AI to evaluate a hardcoded title ("Hustle", type: movie).
3. Gemini AI responds with a JSON verdict, confidence score, reasoning, and potential mismatches.
4. The app cleans and formats the response, displaying it on the web page.

### Example Form Fields
- Genres you like/dislike (comma-separated)
- Preferred pace (slow, medium, fast)
- Emotional tolerance (light, moderate, heavy)
- Goal (relax, think, escape)

### Example Output
```
PICK (Confidence: 0.85)
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
1. Clone the repository:
   ```bash
   git clone <repo-url>
   cd PoP
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your Gemini API key in a `.env` file:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

### Running the Application
1. Start the app:
   ```bash
   python app.py
   ```
2. Open your browser and go to `http://localhost:5000`

## File Details

- `app.py`: Flask app, Gemini API integration, form handling, response formatting
- `requirements.txt`: Flask, google-genai, python-dotenv
- `static/`: Static files (if any)
- `templates/index.html`: Main HTML form and result display

## License
Specify your license here (e.g., MIT).
