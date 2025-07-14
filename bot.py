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
    redirect,
    url_for,
)
from pymongo import MongoClient, DESCENDING
from bson.objectid import ObjectId
from bson.errors import InvalidId
from functools import wraps
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ======================================================================
# --- Environment Variables & Configuration ---
# ======================================================================
MONGO_URI = os.environ.get("MONGO_URI")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
VITE_SITENAME = os.environ.get("VITE_SITENAME", "MovieZone")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "a_very_secret_key_for_flask")

# ======================================================================
# --- HTML, CSS, and JS Templates ---
# ======================================================================

base_layout_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>{{ seo.title or sitename }}</title>
    <meta name="description" content="{{ seo.description or 'Watch movies and series online.' }}" />
    <meta name="keywords" content="{{ seo.keywords or 'movies, series, watch online' }}" />
    <link rel="icon" type="image/svg+xml" href="https://nlmovies.vercel.app/src/assets/images/logo.png" />
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
        :root { 
            --main-bg: #101010; 
            --card-bg: #181818; 
            --text-light: #fff; 
            --text-grey: #aaa; 
            --accent: #50B498; 
            --header-bg: rgba(16, 16, 16, 0.8);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Roboto', sans-serif; background-color: var(--main-bg); color: var(--text-light); line-height: 1.5; }
        .container { max-width: 1400px; margin: 0 auto; padding: 0 15px; }
        a { text-decoration: none; color: inherit; }
        img { max-width: 100%; display: block; }

        .header { 
            padding: 1rem 0; 
            background-color: var(--header-bg); 
            backdrop-filter: blur(10px); 
            position: fixed; top: 0; left: 0; right: 0; z-index: 50; 
            border-bottom: 1px solid #222;
        }
        .header-content { display:flex; justify-content:space-between; align-items:center; }
        .logo { font-size: 1.8rem; font-weight: 700; color: var(--accent); }
        .search-form { width: 40%; }
        .search-form input { background: #222; border: 1px solid #333; color: var(--text-light); padding: 10px 15px; border-radius: 5px; font-size: 1rem; width: 100%; transition: all 0.2s; }
        .search-form input:focus { border-color: var(--accent); background: #2a2a2a; outline: none; }
        .nav-links { display: none; }
        
        main { padding-top: 100px; }
        
        /* Movie Grid - মোবাইল ডিভাইসে ২টি কলাম */
        .grid-title { font-size: 1.5rem; font-weight: 500; margin-bottom: 20px; }
        .movie-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }
        
        .movie-card { 
            cursor: pointer; background: var(--card-bg); 
            border-radius: 5px; overflow: hidden; 
            transition: transform 0.2s, box-shadow 0.2s; 
            position: relative; border: 1px solid transparent; 
        }
        .movie-card:hover { 
            transform: scale(1.05); 
            border-color: var(--accent);
            box-shadow: 0 0 15px rgba(80, 180, 152, 0.3); 
        }
        .movie-card img { width: 100%; aspect-ratio: 2 / 3; object-fit: cover; }
        .movie-card-title { padding: 10px; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        /* Hero Section */
        .hero-section { height: 60vh; position: relative; display: flex; align-items: flex-end; margin-bottom: 40px; border-radius: 10px; overflow: hidden; }
        .hero-bg-img { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; z-index: -2; }
        .hero-gradient { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(to top, var(--main-bg) 5%, transparent 50%); z-index: -1; }
        .hero-content { padding: 20px; position: relative; z-index: 1; }
        .hero-title { font-size: 2rem; font-weight: 700; margin-bottom: 10px; text-shadow: 2px 2px 8px rgba(0,0,0,0.7); }
        .hero-button { padding: 10px 25px; border-radius: 5px; font-weight: 700; text-decoration: none; border: none; cursor: pointer; transition: transform 0.2s; background-color: var(--accent); color: black; display: inline-flex; align-items: center; gap: 8px; }

        /* Detail Page */
        .detail-container { position: relative; display: flex; align-items: center; padding: 20px 0; }
        .detail-backdrop { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; filter: blur(15px) brightness(0.3); transform: scale(1.1); z-index: -1; }
        .detail-content { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 20px; width: 100%; }
        .detail-poster img { width: 60%; max-width: 250px; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); margin: 0 auto; }
        .detail-title { font-size: 2.2rem; margin-bottom: 10px; }
        .detail-meta { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 1rem; margin-bottom: 1rem; color: var(--text-grey); font-size: 0.9rem; }
        .detail-overview { max-width: 600px; line-height: 1.6; margin-bottom: 20px; }
        .detail-actions-title { font-size: 1.5rem; margin: 20px 0 15px 0; border-bottom: 2px solid var(--accent); display: inline-block; padding-bottom: 5px; }
        .detail-actions { display: flex; flex-direction: column; align-items: center; gap: 1rem; width: 100%; }
        .action-button { display:flex; justify-content: center; align-items:center; gap:0.5rem; background-color: #333; color: white; padding: 12px 25px; border-radius: 5px; width: 90%; max-width: 300px; font-weight: 500; }
        .action-button.play { background-color: var(--accent); color: black; }

        .footer { padding: 40px 20px; border-top: 1px solid #222; margin-top: 40px; text-align: center; color: var(--text-grey); font-size: 0.9rem; }

        /* ডেস্কটপ এবং বড় স্ক্রিনের জন্য মিডিয়া কোয়েরি */
        @media (min-width: 768px) {
            .container { padding: 0 40px; }
            .nav-links { display: flex; gap: 2rem; }
            .search-form { width: 33.33%; }
            .movie-grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 20px; }
            .hero-content { padding: 40px; }
            .hero-title { font-size: 3.5rem; }
            .detail-content { flex-direction: row; text-align: left; align-items: flex-start; }
            .detail-poster img { width: 300px; max-width: none; }
            .detail-meta { justify-content: flex-start; }
            .detail-actions { align-items: flex-start; }
            .action-button { width: auto; }
        }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
    <header class="header">
        <div class="container header-content">
            <a href="/" class="logo">{{ sitename }}</a>
            <nav class="nav-links">
                <a href="/" class="nav-link {% if request.path == url_for('home') %}active{% endif %}">Home</a>
                <a href="{{ url_for('movies_page') }}" class="nav-link {% if 'movies' in request.path %}active{% endif %}">Movies</a>
                <a href="{{ url_for('series_page') }}" class="nav-link {% if 'series' in request.path %}active{% endif %}">Series</a>
            </nav>
            <form method="GET" action="{{ url_for('search_page') }}" class="search-form">
                <input type="search" name="q" placeholder="Search..." value="{{ query or '' }}" />
            </form>
        </div>
    </header>
    <main class="container">{{ page_content|safe }}</main>
    <footer class="footer">
        <div class="container">
            <p>This site does not store any file on the server, it only links to media files which are hosted on Telegram.</p>
            <p style="margin-top: 1rem;">© {{ now.year }} {{ sitename }}. All Rights Reserved.</p>
        </div>
    </footer>
</body>
</html>
"""

home_html_content = """
    {% if hero_movie %}
    <section class="hero-section">
        <img src="{{ hero_movie.backdrop or hero_movie.poster }}" alt="{{ hero_movie.title }} backdrop" class="hero-bg-img">
        <div class="hero-gradient"></div>
        <div class="hero-content">
            <h1 class="hero-title">{{ hero_movie.title }}</h1>
            <a href="{{ url_for('movie_detail', tmdb_id=hero_movie.tmdb_id) }}" class="hero-button">
                <i class="fas fa-play"></i> Watch Now
            </a>
        </div>
    </section>
    {% endif %}
    <h2 class="grid-title">Latest Movies</h2>
    <div class="movie-grid">
        {% for movie in latest_movies %}
            <a href="{{ url_for('movie_detail', tmdb_id=movie.tmdb_id) }}" class="movie-card">
                <img src="{{ movie.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ movie.title }} poster" loading="lazy">
                <div class="movie-card-title">{{ movie.title }}</div>
            </a>
        {% endfor %}
    </div>
"""
detail_html_content = """
<div class="detail-container">
    <img src="{{ content.backdrop or content.poster or '' }}" class="detail-backdrop" alt="">
    <div class="detail-content">
        <div class="detail-poster">
            <img src="{{ content.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ content.title }}">
        </div>
        <div class="detail-info">
            <h1 class="detail-title">{{ content.title }}</h1>
            <div class="detail-meta">
                {% if content.release_year %}<span>{{ content.release_year }}</span>{% endif %}
                {% if content.rating and content.rating > 0 %}<span><i class="fas fa-star" style="color:#f5c518;"></i> {{ "%.1f"|format(content.rating) }}</span>{% endif %}
                {% if content.genres %}<span>{{ content.genres|join(' • ') }}</span>{% endif %}
            </div>
            <p class="detail-overview">{{ content.overview }}</p>
            <h2 class="detail-actions-title">Available Files</h2>
            <div class="detail-actions">
                {% if content.type == 'movie' and content.files %}
                    {% for file in content.files|sort(attribute='quality', reverse=True) %}
                        <div style="display:flex; flex-wrap:wrap; align-items:center; gap:1rem;">
                            <a href="{{ url_for('player', movie_id=content._id, quality=file.quality) }}" target="_blank" class="action-button play"><i class="fas fa-play"></i> Play {{ file.quality }}</a>
                            <a href="{{ url_for('download_file', movie_id=content._id, quality=file.quality) }}" class="action-button"><i class="fas fa-download"></i> Download {{ file.quality }}</a>
                        </div>
                    {% endfor %}
                {% else %}<p>No files available yet.</p>{% endif %}
            </div>
        </div>
    </div>
</div>
"""
player_html = """<!DOCTYPE html><html><head><title>Watching: {{ title }}</title><style>body,html{margin:0;padding:0;width:100%;height:100%;background-color:#000;overflow:hidden}video{width:100%;height:100%;object-fit:contain}</style></head><body><video controls autoplay controlsList="nodownload"><source src="{{ url_for('stream_file', movie_id=movie_id, quality=quality) }}" type="video/mp4">Your browser does not support this video.</video></body></html>"""

# ======================================================================
# --- Helper & Core Functions ---
# ======================================================================
def render_page(content_template, **kwargs):
    page_content = render_template_string(content_template, **kwargs)
    return render_template_string(base_layout_html, page_content=page_content, **kwargs)
@app.context_processor
def inject_global_vars(): return dict(sitename=VITE_SITENAME, now=datetime.utcnow())
def check_auth(username, password): return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
def authenticate(): return Response('Could not verify access level.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
@wraps(check_auth)
def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password): return authenticate()
        return f(*args, **kwargs)
    return decorated
try:
    client = MongoClient(MONGO_URI); db = client["movie_db"]; movies_collection = db["movies"]; print("SUCCESS: Connected to MongoDB!")
except Exception as e: print(f"FATAL: DB Error: {e}"); sys.exit(1)
def parse_filename(filename):
    cleaned_name = re.sub(r'[\._]', ' ', filename)
    series_match = re.search(r'^(.*?)[\s\._-]*(?:S|Season)[\s\._-]?(\d{1,2})[\s\._-]*(?:E|Episode)[\s\._-]?(\d{1,3})', cleaned_name, re.I)
    if series_match:
        title, season, episode = series_match.groups()
        year_match = re.search(r'\b(19[89]\d|20\d{2})\b', title); year = year_match.group(1) if year_match else None
        title = re.sub(r'\s*\b(19\d{2}|20\d{2})\b\s*', ' ', title).strip()
        return {'type': 'series', 'title': title.strip().title(), 'year': year, 'season': int(season), 'episode': int(episode)}
    year_match = re.search(r'\b(19[89]\d|20\d{2})\b', cleaned_name); year = year_match.group(1) if year_match else None
    title = re.split(r'\b(19\d{2}|20\d{2})\b', cleaned_name)[0].strip()
    junk_words = ['1080p', '720p', '480p', 'BluRay', 'WEB-DL', 'x264', 'x265', 'AAC', 'HDRip', 'HDTV', 'Esub']
    for junk in junk_words: title = re.sub(r'\b' + junk + r'\b', '', title, flags=re.I)
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
        return {"tmdb_id": tmdb_id, "title": res.get("title") or res.get("name"), "poster": f"https://image.tmdb.org/t/p/w500{res.get('poster_path')}" if res.get('poster_path') else None, "backdrop": f"https://image.tmdb.org/t/p/w1280{res.get('backdrop_path')}" if res.get('backdrop_path') else None, "overview": res.get("overview"), "release_year": (res.get("release_date") or res.get("first_air_date", ""))\
.split('-')[0], "genres": [g['name'] for g in res.get("genres", [])], "rating": res.get("vote_average"), "media_type": search_type}
    except Exception as e: print(f"TMDb API error for '{title}': {e}"); return None
def process_movie_list(movie_list):
    processed = []
    for item in movie_list: 
        if '_id' in item: item["_id"] = str(item["_id"])
        processed.append(item)
    return processed
def get_file_details(movie_id, quality):
    try:
        movie = movies_collection.find_one({"_id": ObjectId(movie_id)})
        if not movie: return None, None
        file_id, filename = None, f"{movie.get('title', 'video')}.mkv"
        target_file = next((f for f in movie.get('files', []) if f.get('quality') == quality), None)
        if target_file: file_id = target_file.get('file_id')
        return file_id, filename
    except InvalidId: return None, None

# ======================================================================
# --- Main Website Routes ---
# ======================================================================
@app.route('/')
def home():
    hero_movie = movies_collection.find_one(sort=[('rating', DESCENDING)])
    latest_movies = list(movies_collection.find({"type": "movie"}).sort('created_at', DESCENDING).limit(18))
    seo = {"title": VITE_SITENAME, "description": "Discover a world of entertainment...", "keywords": "watch movies online"}
    return render_page(home_html_content, hero_movie=process_movie_list([hero_movie])[0] if hero_movie else None, latest_movies=process_movie_list(latest_movies), seo=seo)

@app.route('/movie/<int:tmdb_id>')
def movie_detail(tmdb_id):
    content = movies_collection.find_one({"tmdb_id": tmdb_id})
    if not content: return "Content not found", 404
    seo = {"title": f"{content['title']} - {VITE_SITENAME}", "description": content['overview'], "keywords": f"{content['title']}, watch online"}
    return render_page(detail_html_content, content=process_movie_list([content])[0], seo=seo)

@app.route('/player/<movie_id>/<quality>')
def player(movie_id, quality):
    try:
        movie = movies_collection.find_one({"_id": ObjectId(movie_id)})
        return render_template_string(player_html, title=movie['title'], movie_id=movie_id, quality=quality) if movie else ("Movie not found", 404)
    except InvalidId: return "Invalid Movie ID", 400

# Placeholder pages
@app.route('/movies')
def movies_page(): return "All Movies Page - Coming Soon!"
@app.route('/series')
def series_page(): return "All Series Page - Coming Soon!"
@app.route('/search')
def search_page(): return f"Search results for: {request.args.get('q', '')} - Coming Soon!"

@app.route('/stream/<movie_id>/<quality>')
def stream_file(movie_id, quality):
    file_id, _ = get_file_details(movie_id, quality)
    if not file_id: return "File not found.", 404
    try:
        file_info_res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_path = file_info_res.get('result', {}).get('file_path')
        if not file_path: return f"Telegram API Error: {file_info_res.get('description', 'Could not get file path.')}", 500
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        req = requests.get(file_url, stream=True, timeout=60)
        return Response(stream_with_context(req.iter_content(chunk_size=1024*1024)), content_type=req.headers['content-type'])
    except Exception as e: return f"Streaming Error: {e}", 500

@app.route('/download/<movie_id>/<quality>')
def download_file(movie_id, quality):
    file_id, filename = get_file_details(movie_id, quality)
    if not file_id: return "File not found.", 404
    try:
        file_info_res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_path = file_info_res.get('result', {}).get('file_path')
        if not file_path: return f"Telegram API Error: {file_info_res.get('description', 'Could not get file path.')}", 500
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        req = requests.get(file_url, stream=True, timeout=60)
        headers = {'Content-Type': 'application/octet-stream', 'Content-Disposition': f'attachment; filename="{filename}"'}
        return Response(stream_with_context(req.iter_content(chunk_size=1024*1024)), headers=headers)
    except Exception as e: return f"Download Error: {e}", 500

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json();
    if 'channel_post' not in data: return jsonify(status='ok')
    post = data['channel_post']
    if str(post.get('chat', {}).get('id')) != ADMIN_CHANNEL_ID: return jsonify(status='ok')
    file_doc = post.get('video') or post.get('document')
    if not (file_doc and file_doc.get('file_name')): return jsonify(status='ok')
    file_id, filename = file_doc.get('file_id'), file_doc.get('file_name'); print(f"Webhook: Received file '{filename}'")
    parsed_info = parse_filename(filename)
    if not parsed_info or not parsed_info.get('title'): print(f"Webhook FATAL: Could not parse title from '{filename}'"); return jsonify(status='ok')
    print(f"Webhook: Parsed info: {parsed_info}")
    tmdb_data = get_tmdb_details_from_api(parsed_info['title'], parsed_info['type'], parsed_info.get('year'))
    if not tmdb_data: print(f"Webhook FATAL: Could not find TMDb data for '{parsed_info['title']}'"); return jsonify(status='ok')
    print(f"Webhook: Found TMDb data for '{tmdb_data['title']}'")
    quality_match = re.search(r'(\d{3,4})p', filename, re.I); quality = quality_match.group(1) + "p" if quality_match else "HD"
    if parsed_info['type'] == 'movie':
        existing_movie = movies_collection.find_one({"tmdb_id": tmdb_data['tmdb_id']})
        new_file_data = {"quality": quality, "file_id": file_id, "name": filename}
        if existing_movie:
            movies_collection.update_one({"_id": existing_movie['_id']}, {"$pull": {"files": {"quality": quality}}})
            movies_collection.update_one({"_id": existing_movie['_id']}, {"$push": {"files": new_file_data}})
            print(f"Webhook: Updated movie '{tmdb_data['title']}'")
        else:
            movie_doc = {**tmdb_data, "type": "movie", "files": [new_file_data], "created_at": datetime.utcnow()}
            movies_collection.insert_one(movie_doc)
            print(f"Webhook: Created new movie '{tmdb_data['title']}'.")
    return jsonify(status='ok')
    
@app.route('/admin')
@requires_auth
def admin(): return render_template_string("<h1>Admin Panel</h1><p>Content is managed via Telegram.</p>")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
