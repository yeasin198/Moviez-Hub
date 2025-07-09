import os
import re
import requests
from flask import Flask, request, jsonify, abort, render_template_string, redirect, url_for, session, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
from functools import wraps

# ======================================================================
# --- আপনার ব্যক্তিগত ও অ্যাডমিন তথ্য ---
# ======================================================================
MONGO_URI = "mongodb+srv://mesohas358:mesohas358@cluster0.6kxy1vc.mongodb.net/movie_database?retryWrites=true&w=majority&appName=Cluster0"
BOT_TOKEN = "7931162174:AAGK8aSdqoYpZ4bsSXp36dp6zbVnYeenowA"
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"
ADMIN_CHANNEL_ID = "-1002853936940"
BOT_USERNAME = "CTGVideoPlayerBot"
ADMIN_USER = "Nahid270"
ADMIN_PASS = "Nahid270"
# ======================================================================

# --- অ্যাপ্লিকেশন সেটআপ ---
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- ডাটাবেস ও TMDb জেনার কানেকশন ---
content_collection = None
TMDB_GENRES = {}

try:
    client = MongoClient(MONGO_URI)
    db = client.get_database() 
    content_collection = db.content
    client.admin.command('ping')
    print("SUCCESS: MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")

def load_tmdb_genres():
    global TMDB_GENRES
    if not TMDB_API_KEY:
        print("WARNING: TMDB_API_KEY is not set. Cannot load genres.")
        return
    try:
        for genre_type in ['movie', 'tv']:
            url = f"https://api.themoviedb.org/3/genre/{genre_type}/list?api_key={TMDB_API_KEY}"
            res = requests.get(url).json()
            for genre in res.get('genres', []):
                TMDB_GENRES[genre['id']] = genre['name']
        print("SUCCESS: TMDb genres loaded successfully.")
    except Exception as e:
        print(f"WARNING: Could not load TMDb genres. Error: {e}")

# ======================================================================
# --- HTML এবং CSS টেমপ্লেট ---
# ======================================================================

# INDEX_TEMPLATE, ADMIN_TEMPLATE আগের মতোই থাকবে, কোনো পরিবর্তনের প্রয়োজন নেই।
# শুধু DETAIL_TEMPLATE কিছুটা সরল করা হবে।

INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>MovieZone - Your Entertainment Hub</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
    <style>{{ css_code|safe }}</style>
</head>
<body>
    <header class="main-nav"><a href="{{ url_for('index') }}" class="logo">MovieZone</a></header>
    <main>
        <div class="search-container">
            <form method="GET" action="{{ url_for('index') }}" class="search-form">
                <input type="search" name="q" class="search-input" placeholder="Search for a movie or series..." value="{{ search_query or '' }}">
                <button type="submit" class="search-button"><i class="fas fa-search"></i></button>
            </form>
        </div>
        {% if is_search %}
            <div class="content-section">
                <h2 class="section-title">Search Results for '{{ search_query }}'</h2>
                {% if contents|length == 0 %}<p class="no-results">No content found.</p>{% else %}
                    <div class="content-grid">
                        {% for content in contents %}
                            <a href="{{ url_for('content_detail', content_id=content._id) }}" class="movie-card">
                                <div class="poster-wrapper"><img class="movie-poster" loading="lazy" src="{{ content.poster_url or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ content.title }}"></div>
                                <div class="card-body">
                                    <h4 class="card-title">{{ content.title }}</h4>
                                    {% if content.release_year %}<p class="card-meta">{{ content.release_year }}</p>{% endif %}
                                </div>
                            </a>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>
        {% else %}
            {% if featured %}<div class="hero-section" style="background-image: url('{{ featured.poster_url or '' }}');"><div class="hero-overlay"></div><div class="hero-content"><h1 class="hero-title">{{ featured.title }}</h1><p class="hero-description">{{ featured.description|truncate(150) }}</p><a href="{{ url_for('content_detail', content_id=featured._id) }}" class="hero-button"><i class="fas fa-info-circle"></i> View Details</a></div></div>{% endif %}
            {% for category_name, content_list in categories.items() %}<div class="content-section"><h2 class="section-title">{{ category_name }}</h2><div class="content-carousel">
                {% for content in content_list %}<a href="{{ url_for('content_detail', content_id=content._id) }}" class="movie-card"><div class="poster-wrapper"><img class="movie-poster" loading="lazy" src="{{ content.poster_url or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ content.title }}"></div><div class="card-body"><h4 class="card-title">{{ content.title }}</h4>{% if content.release_year %}<p class="card-meta">{{ content.release_year }}</p>{% endif %}</div></a>{% endfor %}
            </div></div>{% endfor %}
        {% endif %}
    </main>
    <nav class="bottom-nav"><a href="{{ url_for('index') }}" class="nav-item active"><i class="fas fa-home"></i><span>Home</span></a><a href="{{ url_for('admin_login') if not session.get('logged_in') else url_for('admin_dashboard') }}" class="nav-item"><i class="fas fa-user-shield"></i><span>Admin</span></a></nav>
    <script> const nav = document.querySelector('.main-nav'); if(nav){ window.addEventListener('scroll', () => { window.scrollY > 50 ? nav.classList.add('scrolled') : nav.classList.remove('scrolled'); }); } </script>
</body>
</html>
"""

DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>{{ content.title if content else "Not Found" }} - MovieZone</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
    <style>{{ css_code|safe }}</style>
</head>
<body>
    <header class="detail-header"><a href="{{ url_for('index') }}" class="back-button"><i class="fas fa-arrow-left"></i> Back to Home</a></header>
    {% if content %}
    <div class="detail-hero" style="min-height: auto; padding-bottom: 60px;">
      <div class="detail-hero-background" style="background-image: url('{{ content.poster_url }}');"></div>
      <div class="detail-content-wrapper">
        <img class="detail-poster" src="{{ content.poster_url or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ content.title }}">
        <div class="detail-info">
          <h1 class="detail-title">{{ content.title }}</h1>
          <div class="detail-meta">
            {% if content.release_year %}<span>{{ content.release_year }}</span>{% endif %}
            {% if content.rating %}<span><i class="fas fa-star" style="color:#f5c518;"></i> {{ "%.1f"|format(content.rating) }}</span>{% endif %}
            {% if content.genres %}<span class="genres">{% for genre in content.genres %}{{ genre }}{% if not loop.last %}, {% endif %}{% endfor %}</span>{% endif %}
          </div>
          <p class="detail-overview">{{ content.description }}</p>
          <h5 class="mb-3">Get from Bot</h5>
          <div class="quality-buttons">
            <a href="https://t.me/{{ bot_username }}?start=get_{{ content._id }}" class="watch-now-btn" target="_blank">
                <i class="fas fa-robot"></i> Get File
            </a>
          </div>
          <p class="text-muted small mt-3">এই লিঙ্কে ক্লিক করলে আপনাকে সরাসরি টেলিগ্রাম বটে নিয়ে যাওয়া হবে এবং ফাইলটি পাঠিয়ে দেওয়া হবে।</p>
        </div>
      </div>
    </div>
    {% else %}
    <div style="display:flex; justify-content:center; align-items:center; height:100vh;"><h2>Content not found.</h2></div>
    {% endif %}
</body>
</html>
"""

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>Admin Panel - MovieZone</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
    <style>{{ css_code|safe }}</style>
</head>
<body>
    <header class="main-nav"><a href="{{ url_for('index') }}" class="logo">MovieZone</a>{% if session.get('logged_in') %}<a href="{{ url_for('admin_logout') }}" class="btn btn-sm btn-outline-light" style="color:white; border-color:white; text-decoration:none;">Logout</a>{% endif %}</header>
    <main>
        <div class="admin-container">
            {% if page_type == 'login' %}
                <h2>Admin Login</h2>
                {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="flash-msg {{category}}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}
                <form method="post" class="admin-form">
                    <div class="form-group"><label for="username">Username</label><input type="text" name="username" required></div>
                    <div class="form-group"><label for="password">Password</label><input type="password" name="password" required></div>
                    <button type="submit">Login</button>
                </form>
            {% elif page_type == 'dashboard' %}
                <h2>Admin Dashboard</h2>
                {% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="flash-msg {{category}}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}
                <div class="table-responsive">
                    <table class="content-table">
                        <thead><tr><th>Poster</th><th>Title</th><th>Type</th><th>Actions</th></tr></thead>
                        <tbody>
                            {% for content in contents %}
                            <tr>
                                <td><img src="{{ content.poster_url or 'https://via.placeholder.com/50x75' }}" alt="poster" width="40"></td>
                                <td style="max-width: 300px; white-space: normal;">{{ content.title }}</td>
                                <td><span class="type-badge type-{{content.type}}">{{ content.type }}</span></td>
                                <td class="action-buttons">
                                    <a href="{{ url_for('admin_edit', content_id=content._id) }}" class="edit-btn">Edit</a>
                                    <a href="{{ url_for('admin_delete', content_id=content._id) }}" class="delete-btn" onclick="return confirm('Are you sure?');">Delete</a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            {% elif page_type == 'edit' %}
                <h2>Edit: {{ content.title }}</h2>
                <form method="post" class="admin-form"><div class="form-group"><label for="title">Title</label><input type="text" name="title" value="{{ content.title }}" required></div><div class="form-group"><label for="description">Description</label><textarea name="description" rows="5">{{ content.description }}</textarea></div><div class="form-group"><label for="poster_url">Poster URL</label><input type="url" name="poster_url" value="{{ content.poster_url }}"></div><button type="submit">Save Changes</button><a href="{{ url_for('admin_dashboard') }}" class="cancel-link">Cancel</a></form>
            {% endif %}
        </div>
    </main>
</body>
</html>
"""

CSS_CODE = """
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
:root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; --text-dark: #a0a0a0; --nav-height: 60px; --card-gap: 15px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Roboto', sans-serif; background-color: var(--netflix-black); color: var(--text-light); overflow-x: hidden; }
a { text-decoration: none; color: inherit; }
.main-nav { position: fixed; top: 0; left: 0; width: 100%; padding: 15px 50px; display: flex; justify-content: space-between; align-items: center; z-index: 1000; transition: background-color 0.3s ease; background: linear-gradient(to bottom, rgba(0,0,0,0.8) 10%, rgba(0,0,0,0)); }
.main-nav.scrolled { background-color: var(--netflix-black); }
.logo { font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: var(--netflix-red); font-weight: 700; letter-spacing: 1px; }
.search-container { padding: 90px 50px 0px 50px; display: flex; justify-content: center; margin-bottom: 30px; }
.search-form { position: relative; width: 100%; max-width: 600px; }
.search-input { width: 100%; padding: 15px 50px 15px 20px; font-size: 1rem; color: var(--text-light); background-color: #333; border: 1px solid #444; border-radius: 4px; }
.search-input:focus { outline: none; border-color: var(--netflix-red); box-shadow: 0 0 0 3px rgba(229, 9, 20, 0.25); }
.search-input::placeholder { color: var(--text-dark); }
.search-button { position: absolute; top: 0; right: 0; bottom: 0; background: transparent; border: none; color: var(--text-dark); padding: 0 15px; cursor: pointer; font-size: 1.2rem; }
.no-results { text-align:center; color: var(--text-dark); margin-top: 40px; font-size: 1.2rem; }
.hero-section { position: relative; height: 60vh; min-height: 450px; display: flex; align-items: flex-end; padding: 50px; background-size: cover; background-position: center top; margin-top: calc(-1 * var(--nav-height)); }
.hero-overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, var(--netflix-black) 10%, transparent 50%), linear-gradient(to right, rgba(20,20,20,0.7) 0%, transparent 60%); }
.hero-content { position: relative; z-index: 2; max-width: 50%; }
.hero-title { font-family: 'Bebas Neue', sans-serif; font-size: 4rem; margin-bottom: 15px; line-height: 1; text-shadow: 2px 2px 10px rgba(0,0,0,0.7); }
.hero-description { font-size: 1.1rem; line-height: 1.5; margin-bottom: 25px; color: var(--text-light); text-shadow: 1px 1px 5px rgba(0,0,0,0.5); }
.hero-button { background-color: rgba(255, 255, 255, 0.9); color: #000; padding: 10px 25px; font-weight: 700; border-radius: 4px; display: inline-flex; align-items: center; gap: 10px; }
.content-section { padding: 0 50px; margin-bottom: 40px; overflow: hidden; }
.section-title { font-size: 1.8rem; font-weight: 700; margin-bottom: 20px; }
.content-carousel { display: flex; gap: var(--card-gap); overflow-x: auto; overflow-y: hidden; padding-bottom: 20px; margin: 0 -50px; padding-left: 50px; padding-right: 50px; scrollbar-width: none; -ms-overflow-style: none; }
.content-carousel::-webkit-scrollbar { display: none; }
.content-carousel .movie-card { flex: 0 0 calc((100% / 6) - var(--card-gap)); min-width: 160px; }
.content-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--card-gap); }
.movie-card { display: flex; flex-direction: column; background-color: transparent; transition: transform 0.2s ease-out; position: relative; z-index: 1; }
.poster-wrapper { border-radius: 5px; overflow: hidden; position: relative; aspect-ratio: 2 / 3; background-color: #222; }
.movie-poster { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-body { padding: 12px 5px 0 5px; }
.card-title { font-size: 1rem; font-weight: 500; color: var(--text-light); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-meta { font-size: 0.9rem; color: var(--text-dark); margin-top: 4px; }
@media (hover: hover) { .movie-card:hover { transform: scale(1.1); z-index: 10; } .movie-card:hover .poster-wrapper { box-shadow: 0 0 20px rgba(0, 0, 0, 0.8); } }
.bottom-nav { display: none; position: fixed; bottom: 0; left: 0; right: 0; height: var(--nav-height); background-color: #181818; border-top: 1px solid #282828; justify-content: space-around; align-items: center; z-index: 200; }
.nav-item { display: flex; flex-direction: column; align-items: center; color: var(--text-dark); font-size: 10px; flex-grow: 1; padding: 5px 0; }
.nav-item i { font-size: 20px; margin-bottom: 4px; }
.nav-item.active { color: var(--text-light); }
.nav-item.active i { color: var(--netflix-red); }
.detail-header { position: absolute; top: 0; left: 0; right: 0; padding: 20px 50px; z-index: 100; background: linear-gradient(to bottom, rgba(0,0,0,0.7) 10%, transparent); }
.back-button { color: var(--text-light); font-size: 1.2rem; font-weight: 700; display: flex; align-items: center; gap: 10px; }
.detail-hero { position: relative; width: 100%; display: flex; align-items: center; justify-content: center; padding: 120px 0 60px; }
.detail-hero-background { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background-size: cover; background-position: center; filter: blur(20px) brightness(0.4); transform: scale(1.1); }
.detail-hero::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, rgba(20,20,20,1) 0%, rgba(20,20,20,0.6) 50%, rgba(20,20,20,1) 100%); }
.detail-content-wrapper { position: relative; z-index: 2; display: flex; gap: 40px; max-width: 1200px; padding: 0 50px; width: 100%; }
.detail-poster { width: 300px; height: 450px; flex-shrink: 0; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); object-fit: cover; }
.detail-info { flex-grow: 1; max-width: 65%; }
.detail-title { font-family: 'Bebas Neue', sans-serif; font-size: 4.5rem; font-weight: 700; line-height: 1.1; margin-bottom: 20px; }
.detail-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 15px 20px; margin-bottom: 25px; font-size: 1rem; color: var(--text-dark); }
.detail-meta span { font-weight: 700; color: var(--text-light); }
.detail-meta .genres { font-weight: normal; color: var(--text-dark); }
.detail-overview { font-size: 1.1rem; line-height: 1.6; margin-bottom: 30px; }
.quality-buttons a.watch-now-btn { display: inline-block; margin-right: 10px; margin-bottom: 10px; }
.watch-now-btn { background-color: var(--netflix-red); color: white; padding: 12px 25px; font-size: 1rem; font-weight: 700; border: none; border-radius: 5px; cursor: pointer; display: inline-flex; align-items: center; gap: 10px; }
.admin-container { padding: 100px 20px 40px; max-width: 1000px; margin: 0 auto; }
.admin-form { background: #222; padding: 25px; border-radius: 8px; }
.form-group { margin-bottom: 15px; } .form-group label { display: block; margin-bottom: 8px; font-weight: bold; }
input[type="text"], input[type="url"], input[type="password"], textarea { width: 100%; padding: 12px; border-radius: 4px; border: 1px solid #333; font-size: 1rem; background: #333; color: var(--text-light); }
.admin-form button { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1rem; width: 100%; }
.flash-msg { padding: 1rem; margin-bottom: 1rem; border-radius: 4px; }
.flash-msg.success { background-color: #1f4e2c; color: #d4edda; } .flash-msg.error { background-color: #721c24; color: #f8d7da; }
.table-responsive { overflow-x: auto; } .content-table { width: 100%; border-collapse: collapse; }
.content-table th, .content-table td { padding: 12px; text-align: left; border-bottom: 1px solid #333; vertical-align: middle; }
.content-table th { background: #252525; } .action-buttons { display: flex; gap: 10px; }
.action-buttons a { padding: 6px 12px; border-radius: 4px; text-decoration: none; color: white; font-size: 0.9em; }
.edit-btn { background: #0d6efd; } .delete-btn { background: #dc3545; }
.type-badge { display: inline-block; margin: 2px; color: #fff; padding: 0.25em 0.6em; border-radius: 0.25rem; font-size: .8em; font-weight: 700; text-transform: uppercase; }
.type-badge.type-movie { background-color: #198754; } .type-badge.type-tv { background-color: #fd7e14; }
.cancel-link { display: inline-block; margin-top: 10px; color: var(--text-dark); }
@media (max-width: 768px) { body { padding-bottom: var(--nav-height); } .main-nav { padding: 10px 15px; } .logo { font-size: 24px; } .search-container { padding: 80px 15px 0px 15px; } .hero-section { height: 50vh; padding: 15px; align-items: center; text-align: center; } .hero-content { max-width: 100%; } .hero-title { font-size: 2.5rem; } .hero-description { display: none; } .content-section { padding: 0 15px; margin-right: -15px; margin-left: -15px; } .content-carousel { margin: 0; padding-left: 15px; padding-right: 15px; } .content-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); } .content-carousel .movie-card { flex-basis: calc((100% / 3) - var(--card-gap)); min-width: 110px; } .bottom-nav { display: flex; } .detail-content-wrapper { flex-direction: column; align-items: center; text-align: center; padding: 0 20px; } .detail-info { max-width: 100%; } .detail-title { font-size: 3rem; } .detail-poster { width: 60%; max-width: 220px; height: auto; } }
"""

# ======================================================================
# --- Helper Functions (ফাংশনগুলোতে প্রধান পরিবর্তন) ---
# ======================================================================

@app.context_processor
def inject_global_vars():
    return dict(bot_username=BOT_USERNAME)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def parse_filename(filename):
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    base_name = re.sub(r'(\d{3,4}p|web-?dl|hdrip|bluray|x264|x265|hevc|axxo|yify|pack|complete|final|dual audio|hindi).*$', '', cleaned_name, flags=re.IGNORECASE).strip()
    series_match = re.search(r'^(.*?)[\s\._-]*[sS](\d+)[eE](\d+)', base_name, re.IGNORECASE)
    if series_match:
        return {'type': 'tv', 'title': series_match.group(1).strip(), 'season': int(series_match.group(2)), 'episode': int(series_match.group(3))}
    season_pack_match = re.search(r'^(.*?)[\s\._-]*[sS](\d+)', base_name, re.IGNORECASE)
    if season_pack_match:
        return {'type': 'tv', 'title': season_pack_match.group(1).strip(), 'season': int(season_pack_match.group(2)), 'episode': None}
    movie_match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', base_name, re.IGNORECASE)
    if movie_match:
        return {'type': 'movie', 'title': movie_match.group(1).strip(), 'year': movie_match.group(2).strip()}
    return {'type': 'movie', 'title': base_name, 'year': None}

def get_tmdb_info(parsed_info):
    search_type = parsed_info['type']
    api_url = f"https://api.themoviedb.org/3/search/{search_type}"
    params = {'api_key': TMDB_API_KEY, 'query': parsed_info['title']}
    if search_type == 'movie' and parsed_info.get('year'):
        params['primary_release_year'] = parsed_info.get('year')
    try:
        r = requests.get(api_url, params=params)
        r.raise_for_status()
        res = r.json()
        if res.get('results'):
            data = res['results'][0]
            poster = data.get('poster_path')
            genre_ids = data.get('genre_ids', [])
            genres = [TMDB_GENRES.get(gid) for gid in genre_ids if TMDB_GENRES.get(gid)]
            if search_type == 'movie':
                title, year = data.get('title'), data.get('release_date', '')[:4]
            else:
                base_title = data.get('name')
                if parsed_info.get('episode') is not None:
                    title = f"{base_title} - S{parsed_info['season']:02d}E{parsed_info['episode']:02d}"
                else:
                    title = f"{base_title} - Season {parsed_info['season']} Pack"
                year = data.get('first_air_date', '')[:4]
            return {
                'type': search_type, 'title': title, 'description': data.get('overview'),
                'poster_url': f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                'release_year': year, 'rating': round(data.get('vote_average', 0), 1), 'genres': genres[:3]
            }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching TMDb info for '{parsed_info['title']}': {e}")
    return None

# ======================================================================
# --- Flask Routes ---
# ======================================================================

@app.route('/')
def index():
    if content_collection is None: return "Database connection failed.", 500
    search_query = request.args.get('q', '').strip()
    if search_query:
        query = {'title': {'$regex': search_query, '$options': 'i'}}
        search_results = list(content_collection.find(query).sort('_id', -1))
        return render_template_string(INDEX_TEMPLATE, is_search=True, contents=search_results, css_code=CSS_CODE, search_query=search_query)
    else:
        DESIRED_GENRES = ["Action", "Comedy", "Horror", "Thriller", "Science Fiction", "Drama"]
        categories = {}
        featured_content = content_collection.find_one(sort=[('_id', -1)])
        categories['Latest Additions'] = list(content_collection.find().sort('_id', -1).limit(20))
        for genre in DESIRED_GENRES:
            content_list = list(content_collection.find({'genres': genre}).sort('_id', -1).limit(15))
            if content_list: categories[genre] = content_list
        return render_template_string(INDEX_TEMPLATE, is_search=False, featured=featured_content, categories=categories, css_code=CSS_CODE, search_query='')

@app.route('/content/<content_id>')
def content_detail(content_id):
    if content_collection is None: return "Database connection failed.", 500
    try:
        content = content_collection.find_one({'_id': ObjectId(content_id)})
        if content: return render_template_string(DETAIL_TEMPLATE, content=content, css_code=CSS_CODE)
        else: abort(404)
    except: abort(404)

# --- Admin Routes (অপরিবর্তিত) ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if session.get('logged_in'): return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USER and request.form['password'] == ADMIN_PASS:
            session['logged_in'] = True; flash('Login successful!', 'success'); return redirect(url_for('admin_dashboard'))
        else: flash('Invalid credentials.', 'error')
    return render_template_string(ADMIN_TEMPLATE, page_type='login', css_code=CSS_CODE)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    all_content = list(content_collection.find().sort('_id', -1))
    return render_template_string(ADMIN_TEMPLATE, page_type='dashboard', contents=all_content, css_code=CSS_CODE)

@app.route('/admin/edit/<content_id>', methods=['GET', 'POST'])
@login_required
def admin_edit(content_id):
    content = content_collection.find_one({'_id': ObjectId(content_id)})
    if request.method == 'POST':
        updated_data = {'title': request.form['title'], 'description': request.form['description'], 'poster_url': request.form['poster_url']}
        content_collection.update_one({'_id': ObjectId(content_id)}, {'$set': updated_data})
        flash('Content updated successfully!', 'success'); return redirect(url_for('admin_dashboard'))
    return render_template_string(ADMIN_TEMPLATE, page_type='edit', content=content, css_code=CSS_CODE)

@app.route('/admin/delete/<content_id>')
@login_required
def admin_delete(content_id):
    content_collection.delete_one({'_id': ObjectId(content_id)})
    flash('Content deleted successfully!', 'success'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None); flash('You have been logged out.', 'success'); return redirect(url_for('admin_login'))

# --- Webhook Route (প্রধান পরিবর্তন) ---
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    if content_collection is None: return jsonify(status='error', message='Database not connected'), 500
    data = request.get_json()

    if 'channel_post' in data:
        post = data['channel_post']
        if str(post['chat']['id']) == ADMIN_CHANNEL_ID:
            file = post.get('video') or post.get('document')
            if not (file and file.get('file_name')): return jsonify(status='ok')
            
            parsed_info = parse_filename(file['file_name'])
            if not parsed_info.get('title'): return jsonify(status='ok')
            
            tmdb_data = get_tmdb_info(parsed_info)
            if not tmdb_data: return jsonify(status='ok')

            # প্রতিটি ফাইলের জন্য নতুন ডেটা তৈরি করা হচ্ছে
            final_data = tmdb_data.copy()
            final_data['message_id'] = post['message_id']
            
            content_collection.insert_one(final_data)
            print(f"[DB-SUCCESS] Saved new post: '{final_data['title']}'")

    elif 'message' in data:
        message = data['message']
        chat_id, text = message['chat']['id'], message.get('text', '')
        if text.startswith('/start get_'):
            try:
                content_id_str = text.split('_')[1]
                content = content_collection.find_one({'_id': ObjectId(content_id_str)})
                if content and content.get('message_id'):
                    payload = {'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': content['message_id']}
                    res = requests.post(f"{TELEGRAM_API_URL}/copyMessage", json=payload)
                    if not res.json().get('ok'):
                         requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, could not send the file.")
                else: requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, the requested file could not be found.")
            except Exception as e:
                print(f"CRITICAL ERROR on file request: {e}")
                requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=An unexpected error occurred.")
        elif text == '/start':
            requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Welcome! Browse our website to get your file.")
            
    return jsonify(status='ok')

# ======================================================================
# --- Run Application ---
# ======================================================================

if __name__ == '__main__':
    load_tmdb_genres()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
