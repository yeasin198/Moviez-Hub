import os
import sys
import re
import requests
from flask import (
    Flask,
    render_template_string,
    request,
    Response,
    jsonify,
    stream_with_context,
    send_from_directory,
    session,
    redirect,
    url_for,
)
from pymongo import MongoClient, DESC
from bson.objectid import ObjectId
from functools import wraps
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

# ======================================================================
# --- আপনার ব্যক্তিগত ও অ্যাডমিন তথ্য (এনভায়রনমেন্ট থেকে লোড হবে) ---
# ======================================================================
MONGO_URI = os.environ.get("MONGO_URI")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
VITE_SITENAME = os.environ.get("VITE_SITENAME", "MovieZone")
# Note: Firebase and other frontend keys will be handled by the frontend build process
# and injected into the HTML.

# ======================================================================
# --- অ্যাপ্লিকেশন সেটআপ ---
# ======================================================================
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
# Serve React build files from the 'build' directory
app = Flask(__name__, static_folder="build/static", template_folder="build")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "a_very_secret_key")

# ======================================================================
# --- HTML Template (This will be the main entry point for the React App) ---
# ======================================================================
# This is a placeholder. The actual index.html will be served from the 'build' folder.
# The React build process will create this folder and its contents.
# For now, we will create a catch-all route to serve the React app.

# ======================================================================
# --- Helper & Core Functions ---
# ======================================================================

def check_auth(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def authenticate():
    return Response(
        "Could not verify your access level.",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'},
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

try:
    client = MongoClient(MONGO_URI)
    db = client["movie_db"]
    movies_collection = db["movies"]
    print("SUCCESS: Successfully connected to MongoDB!")
except Exception as e:
    print(f"FATAL: Error connecting to MongoDB: {e}. Exiting.")
    sys.exit(1)

def parse_filename(filename):
    cleaned_name = re.sub(r'[\._]', ' ', filename)
    
    # Series pattern: S01E01, Season 01 Episode 01 etc.
    series_match = re.search(r'^(.*?)[\s\._-]*(?:S|Season)[\s\._-]?(\d{1,2})[\s\._-]*(?:E|Episode)[\s\._-]?(\d{1,3})', cleaned_name, re.I)
    if series_match:
        title, season, episode = series_match.groups()
        year_match = re.search(r'\b(19[89]\d|20\d{2})\b', title)
        year = year_match.group(1) if year_match else None
        title = re.sub(r'\s*\b(19\d{2}|20\d{2})\b\s*', ' ', title).strip()
        return {'type': 'series', 'title': title.strip().title(), 'year': year, 'season': int(season), 'episode': int(episode)}

    # Movie pattern
    year_match = re.search(r'\b(19[89]\d|20\d{2})\b', cleaned_name)
    year = year_match.group(1) if year_match else None
    title = re.split(r'\b(19\d{2}|20\d{2})\b', cleaned_name)[0].strip()
    # Remove junk
    junk_words = ['1080p', '720p', '480p', 'BluRay', 'WEB-DL', 'x264', 'x265', 'AAC', 'HDRip', 'HDTV', 'Esub']
    for junk in junk_words:
        title = re.sub(r'\b' + junk + r'\b', '', title, flags=re.I)
    title = re.sub(r'\[.*?\]|\(.*?\)', '', title).strip()
    
    return {'type': 'movie', 'title': title.strip().title(), 'year': year}


def get_tmdb_details_from_api(title, content_type, year=None):
    if not TMDB_API_KEY: return None
    search_type = "tv" if content_type == "series" else "movie"
    try:
        search_url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={TMDB_API_KEY}&query={requests.utils.quote(title)}"
        if year:
            param = "primary_release_year" if search_type == "movie" else "first_air_date_year"
            search_url += f"&{param}={year}"
            
        search_res = requests.get(search_url, timeout=5).json()
        if not search_res.get("results"): return None
        
        tmdb_id = search_res["results"][0].get("id")
        detail_url = f"https://api.themoviedb.org/3/{search_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        res = requests.get(detail_url, timeout=5).json()
        
        return {
            "tmdb_id": tmdb_id,
            "title": res.get("title") or res.get("name"),
            "poster": f"https://image.tmdb.org/t/p/w500{res.get('poster_path')}" if res.get('poster_path') else None,
            "backdrop": f"https://image.tmdb.org/t/p/w1280{res.get('backdrop_path')}" if res.get('backdrop_path') else None,
            "overview": res.get("overview"),
            "description": res.get("overview"), # for compatibility
            "release_year": (res.get("release_date") or res.get("first_air_date", "")).split('-')[0],
            "genres": [g['name'] for g in res.get("genres", [])],
            "rating": res.get("vote_average"),
            "media_type": search_type,
            # Add other fields as needed
        }
    except Exception as e:
        print(f"TMDb API error for '{title}': {e}")
        return None

def process_movie_list(movie_list):
    processed = []
    for item in movie_list:
        item["_id"] = str(item["_id"])
        processed.append(item)
    return processed

def get_file_details(movie_id, quality, season=None, episode=None):
    try:
        movie = movies_collection.find_one({"_id": ObjectId(movie_id)})
        if not movie: return None, None
        
        file_id, filename = None, f"{movie.get('title', 'video')}.mkv"
        if movie.get('type') == 'series' and season and episode:
            # Logic for series (to be implemented if needed)
            pass
        elif movie.get('type') == 'movie':
            target_file = next((f for f in movie.get('files', []) if f.get('quality') == quality), None)
            if target_file: file_id = target_file.get('file_id')
        
        return file_id, filename
    except Exception:
        return None, None

# ======================================================================
# --- API Routes (for the React Frontend) ---
# ======================================================================

@app.route("/api/movies", methods=["GET"])
def api_get_movies():
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))
    sort_by_str = request.args.get('sort_by', 'created_at:desc')
    
    sort_field, sort_order = sort_by_str.split(':')
    sort_direction = DESC if sort_order == 'desc' else 1
    
    query_filter = {"type": "movie"}
    
    total_count = movies_collection.count_documents(query_filter)
    movies_cursor = movies_collection.find(query_filter).sort(sort_field, sort_direction).skip((page - 1) * page_size).limit(page_size)
    
    return jsonify({
        "movies": process_movie_list(list(movies_cursor)),
        "total_count": total_count,
        "current_page": page,
        "total_pages": (total_count + page_size - 1) // page_size
    })

@app.route("/api/id/<tmdb_id>", methods=["GET"])
def api_get_by_id(tmdb_id):
    # This route needs to be compatible with both movie and series ID lookups
    # For simplicity, we assume tmdb_id is used for lookup
    content = movies_collection.find_one({"tmdb_id": int(tmdb_id)})
    if content:
        return jsonify(process_movie_list([content])[0])
    return jsonify({"error": "Content not found"}), 404

@app.route("/api/search/", methods=["GET"])
def api_search():
    query = request.args.get('query', '')
    if not query:
        return jsonify({"results": []})
    
    search_results = movies_collection.find({"title": {"$regex": query, "$options": "i"}}).limit(20)
    return jsonify({"results": process_movie_list(list(search_results))})


# Add other API routes like /api/tvshows, /api/similar as needed based on frontend code

# ======================================================================
# --- Streaming & Downloading Routes ---
# ======================================================================

@app.route('/stream/<movie_id>/<quality>')
@app.route('/stream/<movie_id>/<quality>/<season>/<episode>')
def stream_file(movie_id, quality, season=None, episode=None):
    file_id, _ = get_file_details(movie_id, quality, season, episode)
    if not file_id: return "File not found in database.", 404
    try:
        file_info_res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        if not file_info_res.get('ok'): return f"Telegram Error: {file_info_res.get('description')}", 500
        
        file_path = file_info_res['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        req = requests.get(file_url, stream=True)
        return Response(stream_with_context(req.iter_content(chunk_size=1024*1024)), content_type=req.headers['content-type'])
    except Exception as e: return f"Streaming Error: {e}", 500

@app.route('/dl/<movie_id>/<filename>') # This route is for compatibility with frontend code
def download_alias(movie_id, filename):
    # Simplified: extract quality from filename
    quality_match = re.search(r'(\d{3,4}p)', filename, re.I)
    quality = quality_match.group(1) if quality_match else "HD"
    return redirect(url_for('download_file', movie_id=movie_id, quality=quality))

@app.route('/download/<movie_id>/<quality>')
@app.route('/download/<movie_id>/<quality>/<season>/<episode>')
def download_file(movie_id, quality, season=None, episode=None):
    file_id, filename = get_file_details(movie_id, quality, season, episode)
    if not file_id: return "File not found in database.", 404
    try:
        file_info_res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        if not file_info_res.get('ok'): return f"Telegram Error: {file_info_res.get('description')}", 500
        
        file_path = file_info_res['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        req = requests.get(file_url, stream=True)
        headers = {'Content-Type': 'application/octet-stream', 'Content-Disposition': f'attachment; filename="{filename}"'}
        return Response(stream_with_context(req.iter_content(chunk_size=1024*1024)), headers=headers)
    except Exception as e: return f"Download Error: {e}", 500

# ======================================================================
# --- Webhook Route ---
# ======================================================================

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' not in data: return jsonify(status='ok')
    post = data['channel_post']
    if str(post.get('chat', {}).get('id')) != ADMIN_CHANNEL_ID: return jsonify(status='ok')
    
    file_doc = post.get('video') or post.get('document')
    if not (file_doc and file_doc.get('file_name')): return jsonify(status='ok')

    file_id, filename = file_doc.get('file_id'), file_doc.get('file_name')
    print(f"Webhook: Received file '{filename}'")
    
    parsed_info = parse_filename(filename)
    if not parsed_info or not parsed_info.get('title'):
        print(f"Webhook FATAL: Could not parse title from '{filename}'")
        return jsonify(status='ok', reason='parsing_failed')
    print(f"Webhook: Parsed info: {parsed_info}")

    tmdb_data = get_tmdb_details_from_api(parsed_info['title'], parsed_info['type'], parsed_info.get('year'))
    if not tmdb_data:
        print(f"Webhook FATAL: Could not find TMDb data for '{parsed_info['title']}'")
        return jsonify(status='ok', reason='no_tmdb_data')
    print(f"Webhook: Found TMDb data for '{tmdb_data['title']}'")

    quality_match = re.search(r'(\d{3,4})p', filename, re.I)
    quality = quality_match.group(1) if quality_match else "HD"
    
    # Movie logic
    if parsed_info['type'] == 'movie':
        existing_movie = movies_collection.find_one({"tmdb_id": tmdb_data['tmdb_id']})
        new_file_data = {"quality": quality, "file_id": file_id, "name": filename}
        if existing_movie:
            movies_collection.update_one({"_id": existing_movie['_id']}, {"$pull": {"files": {"quality": quality}}})
            movies_collection.update_one({"_id": existing_movie['_id']}, {"$push": {"files": new_file_data}})
            print(f"Webhook: Updated movie '{tmdb_data['title']}' with quality '{quality}'.")
        else:
            movie_doc = {**tmdb_data, "type": "movie", "files": [new_file_data], "created_at": datetime.utcnow()}
            movies_collection.insert_one(movie_doc)
            print(f"Webhook: Created new movie '{tmdb_data['title']}'.")

    return jsonify(status='ok')

# ======================================================================
# --- React Frontend Serving ---
# ======================================================================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react_app(path):
    if path != "" and os.path.exists(os.path.join(app.template_folder, path)):
        return send_from_directory(app.template_folder, path)
    else:
        return send_from_directory(app.template_folder, 'index.html')

# ======================================================================
# --- Main Execution ---
# ======================================================================

if __name__ == "__main__":
    # Note: For production, use a Gunicorn server.
    # Example: gunicorn --worker-class gevent --workers 1 --bind 0.0.0.0:5000 app:app
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
