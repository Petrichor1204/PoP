import os
import logging
import urllib.request
import urllib.parse
import urllib.error
import json
from datetime import datetime, timezone

import database

logger = logging.getLogger("pop")

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

CACHE_TTL_SECONDS = 86400  # 24 hours

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w92"


def _http_get(url):
    """Simple HTTP GET that returns parsed JSON or raises on error."""
    req = urllib.request.Request(url, headers={"User-Agent": "PickOrPass/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _cache_key(item_type, title):
    safe = title.lower().strip()
    return f"reviews:{item_type}:{safe}"


def _get_cached(item_type, title):
    key = _cache_key(item_type, title)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return database.get_ai_cache(key, now)


def _set_cached(item_type, title, data):
    key = _cache_key(item_type, title)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    database.set_ai_cache(key, data, now, CACHE_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Movie reviews + watch providers via TMDb
# ---------------------------------------------------------------------------

def fetch_movie_reviews(title):
    """Search TMDb for the movie and return normalised review + provider data."""
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY not configured")

    query = urllib.parse.quote(title)
    search_url = (
        f"https://api.themoviedb.org/3/search/movie"
        f"?api_key={TMDB_API_KEY}&query={query}&language=en-US&page=1"
    )
    search_data = _http_get(search_url)
    results = search_data.get("results", [])
    if not results:
        return None

    # Pick the most popular match
    movie = sorted(results, key=lambda m: m.get("popularity", 0), reverse=True)[0]
    movie_id = movie["id"]
    rating = movie.get("vote_average")
    vote_count = movie.get("vote_count", 0)
    overview = movie.get("overview", "")
    item_url = f"https://www.themoviedb.org/movie/{movie_id}"

    # Fetch critic reviews — each has a URL we can link to
    reviews_url = (
        f"https://api.themoviedb.org/3/movie/{movie_id}/reviews"
        f"?api_key={TMDB_API_KEY}&language=en-US&page=1"
    )
    reviews_data = _http_get(reviews_url)
    snippets = []
    for rev in reviews_data.get("results", [])[:3]:
        content = rev.get("content", "")
        if content:
            snippet_text = content[:220].rstrip()
            if len(content) > 220:
                snippet_text += "…"
            snippets.append({
                "text": snippet_text,
                "url": rev.get("url") or f"{item_url}/reviews",
                "author": rev.get("author", ""),
            })

    # Fetch watch providers (JustWatch data via TMDb)
    providers_url = (
        f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers"
        f"?api_key={TMDB_API_KEY}"
    )
    providers_data = _http_get(providers_url)
    us = providers_data.get("results", {}).get("US", {})
    justwatch_link = us.get("link", item_url)

    where_to_get = []
    # Flatrate = subscription streaming (e.g. Netflix, Prime Video)
    for p in us.get("flatrate", [])[:6]:
        where_to_get.append({
            "name": p["provider_name"],
            "logo_url": f"{TMDB_IMAGE_BASE}{p['logo_path']}",
            "link": justwatch_link,
            "kind": "stream",
        })
    # If nothing on subscription, surface buy/rent options too
    if not where_to_get:
        seen = set()
        for p in (us.get("buy", []) + us.get("rent", []))[:4]:
            if p["provider_name"] not in seen:
                seen.add(p["provider_name"])
                where_to_get.append({
                    "name": p["provider_name"],
                    "logo_url": f"{TMDB_IMAGE_BASE}{p['logo_path']}",
                    "link": justwatch_link,
                    "kind": "buy/rent",
                })

    return normalize_reviews(
        source="TMDb",
        matched_title=movie.get("title", title),
        rating=round(rating, 1) if rating is not None else None,
        rating_max=10,
        vote_count=vote_count,
        overview=overview,
        snippets=snippets,
        item_url=item_url,
        where_to_get=where_to_get,
    )


# ---------------------------------------------------------------------------
# Book reviews + purchase links via Google Books
# ---------------------------------------------------------------------------

def fetch_book_reviews(title):
    """Search Google Books for the book and return normalised review + buy data."""
    if not GOOGLE_BOOKS_API_KEY:
        raise RuntimeError("GOOGLE_BOOKS_API_KEY not configured")

    query = urllib.parse.quote(title)
    url = (
        f"https://www.googleapis.com/books/v1/volumes"
        f"?q={query}&key={GOOGLE_BOOKS_API_KEY}&maxResults=5&langRestrict=en"
    )
    data = _http_get(url)
    items = data.get("items", [])
    if not items:
        return None

    # Prefer exact or close title match; fall back to first result
    best = None
    title_lower = title.lower()
    for item in items:
        info = item.get("volumeInfo", {})
        if title_lower in info.get("title", "").lower():
            best = item
            break
    if not best:
        best = items[0]

    info = best.get("volumeInfo", {})
    sale_info = best.get("saleInfo", {})

    rating = info.get("averageRating")
    vote_count = info.get("ratingsCount", 0)
    overview = info.get("description", "")
    item_url = info.get("infoLink") or info.get("previewLink") or ""

    # Description snippet links to Google Books page
    snippets = []
    if overview:
        snippet_text = overview[:220].rstrip()
        if len(overview) > 220:
            snippet_text += "…"
        snippets.append({
            "text": snippet_text,
            "url": item_url,
            "author": "Publisher description",
        })

    # Build where-to-buy list
    where_to_get = []

    # Amazon search (construct a search URL using the matched title + first author)
    authors = info.get("authors", [])
    amazon_query = urllib.parse.quote(info.get("title", title))
    if authors:
        amazon_query += "+" + urllib.parse.quote(authors[0])
    where_to_get.append({
        "name": "Amazon",
        "logo_url": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg",
        "link": f"https://www.amazon.com/s?k={amazon_query}&i=stripbooks",
        "kind": "buy",
    })

    # Google Play Books (if saleInfo has a buyLink)
    buy_link = sale_info.get("buyLink")
    if buy_link:
        where_to_get.append({
            "name": "Google Play Books",
            "logo_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f3/Google_Play_Books_icon_2022.svg/240px-Google_Play_Books_icon_2022.svg.png",
            "link": buy_link,
            "kind": "buy",
        })

    return normalize_reviews(
        source="Google Books",
        matched_title=info.get("title", title),
        rating=rating,
        rating_max=5,
        vote_count=vote_count,
        overview=overview,
        snippets=snippets,
        item_url=item_url,
        where_to_get=where_to_get,
    )


# ---------------------------------------------------------------------------
# Shared normaliser
# ---------------------------------------------------------------------------

def normalize_reviews(source, matched_title, rating, rating_max, vote_count,
                       overview, snippets, item_url, where_to_get):
    return {
        "source": source,
        "matched_title": matched_title,
        "rating": rating,
        "rating_max": rating_max,
        "vote_count": vote_count,
        "overview": overview,
        "snippets": snippets,      # list of {text, url, author}
        "item_url": item_url,      # link to the canonical page on TMDb / Google Books
        "where_to_get": where_to_get,  # list of {name, logo_url, link, kind}
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_reviews(title, item_type):
    """
    Return cached-or-fresh review data for *title* of *item_type*
    ('movie' or 'book').  Returns None if nothing is found.
    """
    cached = _get_cached(item_type, title)
    if cached is not None:
        logger.info("reviews cache hit: %s / %s", item_type, title)
        return cached

    try:
        if item_type == "movie":
            data = fetch_movie_reviews(title)
        elif item_type == "book":
            data = fetch_book_reviews(title)
        else:
            return None
    except urllib.error.URLError as exc:
        logger.warning("reviews fetch network error: %s", exc)
        return None
    except Exception as exc:
        logger.warning("reviews fetch error: %s", exc)
        return None

    if data:
        _set_cached(item_type, title, data)

    return data
