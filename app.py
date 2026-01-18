from flask import Flask, render_template, request

app = Flask(__name__)

def build_preference_object(form):
    """
    Builds a cleaned and normalized preference object from form data.
    Normalizes string values by stripping whitespace and converting to lowercase.
    Splits comma-separated genres into lists.
    
    Args:
        form: Flask request.form object
        
    Returns:
        dict: Cleaned preference dictionary with normalized string values
    """
    def normalize_value(value, as_list=False):
        """Normalize a string value: strip whitespace, convert to lowercase.
        Optionally split comma-separated values into a list."""
        if value is None:
            return [] if as_list else None
        # Convert to string, strip whitespace, convert to lowercase
        normalized = str(value).strip().lower()
        if not normalized:
            return [] if as_list else None
        
        if as_list:
            # Split by comma, strip each item, and filter out empty strings
            return [item.strip() for item in normalized.split(",") if item.strip()]
        else:
            return normalized
    
    preferences = {
        "likes": normalize_value(form.get("likes"), as_list=True),
        "dislikes": normalize_value(form.get("dislikes"), as_list=True),
        "pace": normalize_value(form.get("pace")),
        "emotional_tolerance": normalize_value(form.get("emotional_tolerance")),
        "goal": normalize_value(form.get("goal"))
    }
    
    return preferences

@app.route("/", methods=["GET", "POST"])
def preferences():
    if request.method == "POST":
        # Build cleaned and normalized preference object
        user_preferences = build_preference_object(request.form)
        
        print(user_preferences)  # proof it works

    return render_template("index.html")

if __name__ == '__main__':
    app.run(debug=True)
