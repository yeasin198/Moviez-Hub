import os
import sys
import re
import requests
from flask import Flask, render_template_string, request, redirect, url_for, Response, jsonify, stream_with_context
from pymongo import MongoClient
from bson.objectid import ObjectId
from functools import wraps
from datetime import datetime

# ======================================================================
# --- আপনার ব্যক্তিগত ও অ্যাডমিন তথ্য (এনভায়রনমেন্ট থেকে লোড হবে) ---
# ======================================================================
MONGO_URI = os.environ.get("MONGO_URI")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# --- প্রয়োজনীয় ভেরিয়েবলগুলো সেট করা হয়েছে কিনা তা পরীক্ষা করা ---
required_vars = {
    "MONGO_URI": MONGO_URI, "BOT_TOKEN": BOT_TOKEN, "TMDB_API_KEY": TMDB_API_KEY,
    "ADMIN_CHANNEL_ID": ADMIN_CHANNEL_ID, "ADMIN_USERNAME": ADMIN_USERNAME, "ADMIN_PASSWORD": ADMIN_PASSWORD,
}

missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    print(f"FATAL: Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

# ======================================================================
# --- অ্যাপ্লিকেশন সেটআপ ---
# ======================================================================
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ======================================================================
# --- HTML টেমপ্লেটগুলো এখানে ভেরিয়েবল হিসেবে থাকবে ---
# ======================================================================

# --- ১. হোমপেজ (index.html) ---
index_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>MovieZone - Your Entertainment Hub</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
        :root { --main-bg: #101010; --card-bg: #181818; --text-light: #fff; --text-grey: #aaa; --accent-red: #e50914; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Roboto', sans-serif; background-color: var(--main-bg); color: var(--text-light); }
        body.modal-open { overflow: hidden; }
        .container { max-width: 1400px; margin: 0 auto; padding: 0 20px; }
        .header { padding: 20px 0; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 2rem; font-weight: 700; color: var(--accent-red); text-decoration: none; }
        .search-form input { background: #222; border: 1px solid #333; color: var(--text-light); padding: 10px 15px; border-radius: 5px; font-size: 1rem; }
        .hero-section { height: 70vh; position: relative; display: flex; align-items: flex-end; margin-bottom: 40px; border-radius: 10px; overflow: hidden; }
        .hero-bg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; z-index: -2; }
        .hero-bg-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(to top, var(--main-bg) 10%, transparent 50%); z-index: -1; }
        .hero-content { padding: 40px; }
        .hero-title { font-size: 3.5rem; font-weight: 700; margin-bottom: 10px; text-shadow: 2px 2px 8px rgba(0,0,0,0.7); }
        .hero-buttons .btn { padding: 10px 25px; border-radius: 5px; font-weight: 700; text-decoration: none; margin-right: 15px; border: none; cursor: pointer; transition: transform 0.2s; }
        .hero-buttons .btn:hover { transform: scale(1.05); }
        .btn-play { background-color: var(--accent-red); color: white; }
        .btn-info { background-color: rgba(109, 109, 110, 0.7); color: white; }
        .category-title { font-size: 1.8rem; font-weight: 500; margin-bottom: 20px; padding-left: 20px; }
        .movie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 20px; }
        .movie-card { cursor: pointer; background: var(--card-bg); border-radius: 5px; overflow: hidden; transition: transform 0.2s; position: relative; }
        .movie-card:hover { transform: scale(1.05); box-shadow: 0 0 15px rgba(229, 9, 20, 0.5); }
        .movie-card img { width: 100%; aspect-ratio: 2/3; object-fit: cover; display: block; }
        .movie-card-title { padding: 10px; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.85); display: none; align-items: center; justify-content: center; z-index: 1001; opacity: 0; transition: opacity 0.2s ease; }
        .modal-overlay.show { display: flex; opacity: 1; }
        .modal-content { background-color: #1f1f1f; padding: 25px; border-radius: 12px; width: 90%; max-width: 380px; position: relative; transform: scale(0.95); transition: transform 0.2s ease; border: 1px solid #333; }
        .modal-overlay.show .modal-content { transform: scale(1); }
        .modal-close { position: absolute; top: 10px; right: 15px; font-size: 28px; cursor: pointer; color: #aaa; transition: color 0.2s; }
        .modal-close:hover { color: white; }
        .modal-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; }
        .modal-link { display: flex; align-items: center; gap: 12px; text-decoration: none; color: white; background: #333; padding: 12px 15px; border-radius: 8px; margin-bottom: 10px; transition: transform 0.2s; }
        .modal-link:hover { transform: scale(1.03); }
        .modal-link.play-btn { background-color: var(--accent-red); }
        .modal-link.info-btn { background: rgba(109, 109, 110, 0.7); margin-top: 15px; border-top: 1px solid #444; padding-top: 15px; }
        .modal-link i { font-size: 1.1rem; width: 20px; text-align: center; }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
    <div class="container">
        <header class="header">
            <a href="/" class="logo">MovieZone</a>
            <form method="GET" action="/" class="search-form">
                <input type="search" name="q" placeholder="Search..." value="{{ query|default('') }}" />
            </form>
        </header>
        
        {% if not is_full_page_list and recently_added %}
        <section class="hero-section">
            <img src="{{ recently_added[0].backdrop or recently_added[0].poster }}" alt="{{ recently_added[0].title }} backdrop" class="hero-bg">
            <div class="hero-bg-overlay"></div>
            <div class="hero-content">
                <h1 class="hero-title">{{ recently_added[0].title }}</h1>
                <div class="hero-buttons">
                    <a href="{{ url_for('player', movie_id=recently_added[0]._id, quality=recently_added[0].files[0].quality) if recently_added[0].files else '#' }}" class="btn btn-play"><i class="fas fa-play"></i> Play</a>
                    <a href="{{ url_for('movie_detail', movie_id=recently_added[0]._id) }}" class="btn btn-info"><i class="fas fa-info-circle"></i> More Info</a>
                </div>
            </div>
        </section>
        {% endif %}

        <h2 class="category-title">{{ query or 'Latest Movies & Series' }}</h2>
        <div class="movie-grid">
            {% set content_list = movies if is_full_page_list else latest_movies %}
            {% for m in content_list %}
            <div class="movie-card"
                data-id="{{ m._id }}"
                data-title="{{ m.title }}"
                data-files="{{ m.files|tojson|safe }}"
                data-type="{{ m.type }}">
                <img src="{{ m.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ m.title }} poster" loading="lazy">
                <div class="movie-card-title">{{ m.title }}</div>
            </div>
            {% endfor %}
        </div>
    </div>

    <div class="modal-overlay" id="linkModal">
      <div class="modal-content">
        <span class="modal-close" id="modalCloseBtn">×</span>
        <h3 class="modal-title" id="modalTitle"></h3>
        <div id="modalLinks"></div>
        <a href="#" id="modalInfoLink" class="modal-link info-btn">
            <i class="fas fa-info-circle"></i> <span>More Info & Details</span>
        </a>
      </div>
    </div>

    <script>
    document.addEventListener('DOMContentLoaded', () => {
        const modalOverlay = document.getElementById('linkModal');
        const modalTitle = document.getElementById('modalTitle');
        const modalLinksContainer = document.getElementById('modalLinks');
        const modalInfoLink = document.getElementById('modalInfoLink');
        const closeModalBtn = document.getElementById('modalCloseBtn');
        document.querySelectorAll('.movie-card').forEach(card => {
            card.addEventListener('click', () => {
                const id = card.dataset.id;
                const title = card.dataset.title;
                const files = JSON.parse(card.dataset.files);
                const type = card.dataset.type;

                modalTitle.textContent = title;
                modalInfoLink.href = `/movie/${id}`;
                modalLinksContainer.innerHTML = '';

                if (type === 'series') {
                    modalLinksContainer.innerHTML = `<a href="/movie/${id}" class="modal-link play-btn"><i class="fas fa-list-ul"></i> <span>View All Episodes</span></a>`;
                } else if (files && files.length > 0) {
                    let linksHtml = '';
                    files.sort((a, b) => (parseInt(b.quality) || 0) - (parseInt(a.quality) || 0)); // Sort by quality DESC
                    files.forEach(file => {
                        const quality = file.quality;
                        linksHtml += `
                            <a href="/player/${id}/${quality}" class="modal-link play-btn" target="_blank"><i class="fas fa-play"></i> <span>Play ${quality}</span></a>
                            <a href="/download/${id}/${quality}" class="modal-link"><i class="fas fa-download"></i> <span>Download ${quality}</span></a>
                        `;
                    });
                    modalLinksContainer.innerHTML = linksHtml;
                } else {
                    modalLinksContainer.innerHTML = '<p>No links available yet.</p>';
                }
                
                document.body.classList.add('modal-open');
                modalOverlay.classList.add('show');
            });
        });

        const closeModal = () => {
            document.body.classList.remove('modal-open');
            modalOverlay.classList.remove('show');
        }
        closeModalBtn.addEventListener('click', closeModal);
        modalOverlay.addEventListener('click', e => { if (e.target === modalOverlay) closeModal(); });
        document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
    });
    </script>
</body>
</html>
"""

# --- ২. বিস্তারিত পেজ (detail.html) ---
detail_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ movie.title }} - MovieZone</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
        :root { --main-bg: #101010; --card-bg: #181818; --text-light: #fff; --text-grey: #aaa; --accent-red: #e50914; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Roboto', sans-serif; background-color: var(--main-bg); color: var(--text-light); }
        .back-button { position: absolute; top: 20px; left: 20px; color: white; text-decoration: none; font-size: 1.2rem; z-index: 10; background: rgba(0,0,0,0.5); padding: 8px 15px; border-radius: 20px; }
        .detail-hero { position: relative; min-height: 80vh; display: flex; align-items: center; padding: 40px; }
        .hero-background { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; filter: blur(10px) brightness(0.4); transform: scale(1.1); }
        .detail-content { position: relative; display: flex; gap: 40px; align-items: center; }
        .detail-poster img { width: 300px; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        .detail-info h1 { font-size: 3rem; margin-bottom: 20px; }
        .detail-meta { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 20px; color: var(--text-grey); }
        .detail-overview { max-width: 600px; line-height: 1.6; margin-bottom: 30px; }
        .section-title { font-size: 1.5rem; margin: 30px 0 15px 0; border-bottom: 2px solid var(--accent-red); display: inline-block; padding-bottom: 5px; }
        .action-links a { display: inline-flex; align-items: center; gap: 10px; background: #222; padding: 15px; border-radius: 5px; text-decoration: none; color: white; margin: 5px; transition: background 0.2s; }
        .action-links a:hover { background: #333; }
        .action-links .play-btn { background-color: var(--accent-red); }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
    <a href="/" class="back-button">← Back</a>
    <div class="detail-hero">
        <img src="{{ movie.backdrop or movie.poster or '' }}" class="hero-background" alt="">
        <div class="detail-content">
            <div class="detail-poster">
                <img src="{{ movie.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ movie.title }}">
            </div>
            <div class="detail-info">
                <h1>{{ movie.title }}</h1>
                <div class="detail-meta">
                    {% if movie.release_date %}<span>{{ movie.release_date.split('-')[0] }}</span>{% endif %}
                    {% if movie.vote_average %}<span><i class="fas fa-star" style="color:#f5c518;"></i> {{ "%.1f"|format(movie.vote_average) }}</span>{% endif %}
                    {% if movie.genres %}<span>{{ movie.genres|join(' • ') }}</span>{% endif %}
                </div>
                <p class="detail-overview">{{ movie.overview }}</p>

                <div>
                    <h2 class="section-title">Available Files</h2>
                    <div class="action-links">
                        {% if movie.type == 'movie' and movie.files %}
                            {% for file in movie.files | sort(attribute='quality', reverse=True) %}
                                <a href="{{ url_for('player', movie_id=movie._id, quality=file.quality) }}" class="play-btn"><i class="fas fa-play"></i> Play {{ file.quality }}</a>
                                <a href="{{ url_for('download_file', movie_id=movie._id, quality=file.quality) }}"><i class="fas fa-download"></i> Download {{ file.quality }}</a>
                            {% endfor %}
                        {% elif movie.type == 'series' and movie.episodes %}
                             {% for ep in movie.episodes | sort(attribute='episode_number') | sort(attribute='season') %}
                                <a href="{{ url_for('player', movie_id=movie._id, quality=ep.quality, season=ep.season, episode=ep.episode_number) }}" class="play-btn">
                                    <i class="fas fa-play"></i> S{{ "%02d"|format(ep.season) }}E{{ "%02d"|format(ep.episode_number) }} - Play {{ ep.quality }}
                                </a>
                            {% endfor %}
                        {% else %}
                            <p>No files available yet.</p>
                        {% endif %}
                    </div>
                </div>

            </div>
        </div>
    </div>
</body>
</html>
"""

# --- ৩. ভিডিও প্লেয়ার (player.html) ---
player_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Watching: {{ movie.title }}</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #000; overflow: hidden; }
        video { width: 100%; height: 100%; object-fit: contain; }
    </style>
</head>
<body>
    <video controls autoplay controlsList="nodownload">
        <source src="{{ url_for('stream_file', movie_id=movie_id, quality=quality, season=season, episode=episode) }}" type="video/mp4">
        Your browser does not support the video tag.
    </video>
</body>
</html>
"""

# --- ৪. অ্যাডমিন প্যানেল (admin_panel.html) ---
admin_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Panel - MovieZone</title>
    <style>
        body { font-family: sans-serif; background: #111; color: #eee; padding: 20px; }
        h1 { color: #e50914; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #444; padding: 8px; text-align: left; vertical-align: middle; }
        th { background: #333; }
        img { border-radius: 4px; }
        a { color: #3498db; }
    </style>
</head>
<body>
    <h1>Manage Content</h1>
    <p>Upload files to your admin Telegram channel to automatically add or update content.</p>
    <table>
        <thead><tr><th>Poster</th><th>Title</th><th>Type</th><th>Available Files</th><th>Actions</th></tr></thead>
        <tbody>
            {% for movie in all_content %}
            <tr>
                <td><img src="{{ movie.poster }}" width="60" alt="poster"></td>
                <td>{{ movie.title }}</td>
                <td>{{ movie.type }}</td>
                <td>
                    {% if movie.files %}
                        {% for file in movie.files %}
                            <span>{{ file.quality }}</span>{% if not loop.last %}, {% endif %}
                        {% endfor %}
                    {% else %}
                        N/A
                    {% endif %}
                </td>
                <td><a href="#">Edit</a> <a href="#">Delete</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</body>
</html>
"""

# ======================================================================
# --- Helper & Core Functions ---
# ======================================================================

# --- অ্যাডমিন অথেন্টিকেশন ফাংশন ---
def check_auth(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def authenticate():
    return Response('Could not verify your access level.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- ডাটাবেস কানেকশন ---
try:
    client = MongoClient(MONGO_URI)
    db = client["movie_db"]
    movies = db["movies"]
    print("SUCCESS: Successfully connected to MongoDB!")
except Exception as e:
    print(f"FATAL: Error connecting to MongoDB: {e}. Exiting.")
    sys.exit(1)

# --- TMDb থেকে তথ্য আনার ফাংশন ---
def get_tmdb_details_from_api(title, content_type, year=None):
    if not TMDB_API_KEY: return None
    search_type = "tv" if content_type == "series" else "movie"
    try:
        search_url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={TMDB_API_KEY}&query={requests.utils.quote(title)}"
        if year and search_type == "movie": search_url += f"&primary_release_year={year}"
        search_res = requests.get(search_url, timeout=5).json()
        if not search_res.get("results"): return None

        tmdb_id = search_res["results"][0].get("id")
        detail_url = f"https://api.themoviedb.org/3/{search_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        res = requests.get(detail_url, timeout=5).json()
        
        return {
            "tmdb_id": tmdb_id, "title": res.get("title") if search_type == "movie" else res.get("name"),
            "poster": f"https://image.tmdb.org/t/p/w500{res.get('poster_path')}" if res.get('poster_path') else None,
            "backdrop": f"https://image.tmdb.org/t/p/w1280{res.get('backdrop_path')}" if res.get('backdrop_path') else None,
            "overview": res.get("overview"), "release_date": res.get("release_date") if search_type == "movie" else res.get("first_air_date"),
            "genres": [g['name'] for g in res.get("genres", [])], "vote_average": res.get("vote_average")
        }
    except requests.RequestException as e:
        print(f"TMDb API error for '{title}': {e}")
    return None

def process_movie_list(movie_list):
    for item in movie_list:
        if '_id' in item: item['_id'] = str(item['_id'])
    return movie_list

def get_file_details(movie_id, quality, season=None, episode=None):
    movie = movies.find_one({"_id": ObjectId(movie_id)})
    if not movie: return None, None, None

    file_id, filename = None, f"{movie.get('title', 'video')}.mp4"

    if movie['type'] == 'series' and season and episode:
        target_episode = next((ep for ep in movie.get('episodes', []) 
                               if ep.get('season') == int(season) and ep.get('episode_number') == int(episode) and ep.get('quality') == quality), None)
        if target_episode: file_id = target_episode.get('file_id')
    elif movie['type'] == 'movie':
        target_file = next((f for f in movie.get('files', []) if f.get('quality') == quality), None)
        if target_file: file_id = target_file.get('file_id')
    
    return file_id, filename, movie

# ======================================================================
# --- Main Website Routes ---
# ======================================================================

@app.route('/')
def home():
    query = request.args.get('q')
    if query:
        movies_list = list(movies.find({"title": {"$regex": query, "$options": "i"}}).sort('_id', -1))
        return render_template_string(index_html, movies=process_movie_list(movies_list), query=f'Results for "{query}"', is_full_page_list=True)

    limit = 12
    context = {
        "latest_movies": process_movie_list(list(movies.find({"type": "movie"}).sort('_id', -1).limit(limit))),
        "recently_added": process_movie_list(list(movies.find().sort('_id', -1).limit(6))),
        "is_full_page_list": False,
    }
    return render_template_string(index_html, **context)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    try:
        movie = movies.find_one({"_id": ObjectId(movie_id)})
        return render_template_string(detail_html, movie=movie) if movie else ("Content not found", 404)
    except Exception as e:
        return f"An error occurred: {e}", 500

# ======================================================================
# --- Streaming and Downloading Routes ---
# ======================================================================

@app.route('/stream/<movie_id>/<quality>')
@app.route('/stream/<movie_id>/<quality>/<season>/<episode>')
def stream_file(movie_id, quality, season=None, episode=None):
    file_id, _, _ = get_file_details(movie_id, quality, season, episode)
    if not file_id: return "File not found in database.", 404
    
    try:
        file_info_res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        if not file_info_res.get('ok'):
            return f"Error getting file info from Telegram: {file_info_res.get('description')}", 500
        
        file_path = file_info_res['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        req = requests.get(file_url, stream=True)
        return Response(stream_with_context(req.iter_content(chunk_size=1024*1024)), content_type=req.headers['content-type'])
    except Exception as e:
        print(f"Streaming Error: {e}")
        return "Error streaming file from server.", 500

@app.route('/download/<movie_id>/<quality>')
@app.route('/download/<movie_id>/<quality>/<season>/<episode>')
def download_file(movie_id, quality, season=None, episode=None):
    file_id, filename, _ = get_file_details(movie_id, quality, season, episode)
    if not file_id: return "File not found in database.", 404

    try:
        file_info_res = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        if not file_info_res.get('ok'): return f"Error from Telegram: {file_info_res.get('description')}", 500

        file_path = file_info_res['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        req = requests.get(file_url, stream=True)
        headers = {'Content-Type': 'application/octet-stream', 'Content-Disposition': f'attachment; filename="{filename}"'}
        return Response(stream_with_context(req.iter_content(chunk_size=1024*1024)), headers=headers)
    except Exception as e:
        print(f"Download Error: {e}")
        return "Error creating download link.", 500

@app.route('/player/<movie_id>/<quality>')
@app.route('/player/<movie_id>/<quality>/<season>/<episode>')
def player(movie_id, quality, season=None, episode=None):
    _, _, movie = get_file_details(movie_id, quality, season, episode)
    if not movie: return "Movie not found", 404
    return render_template_string(player_html, movie=movie, movie_id=movie_id, quality=quality, season=season, episode=episode)

# ======================================================================
# --- Webhook Route ---
# ======================================================================

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' not in data: return jsonify(status='ok', reason='not_a_channel_post')
        
    post = data['channel_post']
    if str(post.get('chat', {}).get('id')) != ADMIN_CHANNEL_ID: return jsonify(status='ok', reason='not_admin_channel')

    file_doc = post.get('video') or post.get('document')
    if not (file_doc and file_doc.get('file_name')): return jsonify(status='ok', reason='no_file_in_post')

    file_id, filename, message_id = file_doc.get('file_id'), file_doc.get('file_name'), post['message_id']
    
    # ফাইলের নাম থেকে টাইটেল এবং সাল বের করার চেষ্টা
    parsed_title = os.path.splitext(filename)[0]
    year_match = re.search(r'\b(19[89]\d|20\d{2})\b', parsed_title)
    year = year_match.group(1) if year_match else None
    parsed_title = re.sub(r'\b(19\d{2}|20\d{2}|480p|720p|1080p|BluRay|WEB-DL|x264|x265|HDRip|HDTV)\b', '', parsed_title, flags=re.I)
    parsed_title = parsed_title.replace('.', ' ').strip()

    tmdb_data = get_tmdb_details_from_api(parsed_title, "movie", year)
    if not tmdb_data:
        print(f"Webhook FATAL: Could not find TMDb data for '{parsed_title}'.")
        return jsonify(status='ok', reason='no_tmdb_data')

    quality_match = re.search(r'(\d{3,4})p', filename, re.I)
    quality = quality_match.group(1) + "p" if quality_match else "HD"

    existing_movie = movies.find_one({"tmdb_id": tmdb_data['tmdb_id']})
    new_file_data = {"quality": quality, "file_id": file_id, "message_id": message_id}

    if existing_movie:
        movies.update_one({"_id": existing_movie['_id']}, {"$pull": {"files": {"quality": quality}}})
        movies.update_one({"_id": existing_movie['_id']}, {"$push": {"files": new_file_data}})
        print(f"Webhook: Updated movie '{tmdb_data['title']}' with quality '{quality}'.")
    else:
        movie_doc = {**tmdb_data, "type": "movie", "files": [new_file_data], "created_at": datetime.utcnow()}
        movies.insert_one(movie_doc)
        print(f"Webhook: Created new movie '{tmdb_data['title']}'.")

    return jsonify(status='ok')

# ======================================================================
# --- Admin Panel Route ---
# ======================================================================
@app.route('/admin')
@requires_auth
def admin():
    all_content = process_movie_list(list(movies.find().sort('_id', -1)))
    return render_template_string(admin_html, all_content=all_content)

# ======================================================================
# --- Main Execution ---
# ======================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
