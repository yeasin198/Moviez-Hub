import os
import re
import requests
from flask import Flask, request, jsonify, abort, render_template_string, redirect, url_for, session, flash, Response
from pymongo import MongoClient
from bson.objectid import ObjectId
from functools import wraps
from datetime import datetime

# ======================================================================
# --- আপনার ব্যক্তিগত ও অ্যাডমিন তথ্য ---
# ======================================================================
MONGO_URI = "mongodb+srv://mesohas358:mesohas358@cluster0.6kxy1vc.mongodb.net/movie_database?retryWrites=true&w=majority&appName=Cluster0"
BOT_TOKEN = "7931162174:AAGK8aSdqoYpZ4bsSXp36dp6zbVnYeenowA"
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"
ADMIN_CHANNEL_ID = "-1002853936940"
BOT_USERNAME = "CTGVideoPlayerBot"
# --- অ্যাডমিন প্যানেলের তথ্য ---
ADMIN_USER = "Nahid270"
ADMIN_PASS = "Nahid270"
# ======================================================================

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Database Connection ---
try:
    client = MongoClient(MONGO_URI)
    db = client["movie_db"]
    content_collection = db["content"]
    settings_collection = db["settings"]
    feedback_collection = db["feedback"]
    client.admin.command('ping')
    print("SUCCESS: MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")
    content_collection = None
    settings_collection = None
    feedback_collection = None

# --- আপনার ডিজাইন থেকে আনা টেমপ্লেট ও CSS ---
# (আমাদের সিস্টেমের সাথে ইন্টিগ্রেট করা)
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
<title>MovieZone - Your Entertainment Hub</title>
<style>{{ css_code|safe }}</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
<header class="main-nav">
  <a href="{{ url_for('home') }}" class="logo">MovieZone</a>
  <form method="GET" action="/" class="search-form">
    <input type="search" name="q" class="search-input" placeholder="Search..." value="{{ query|default('') }}" />
  </form>
</header>
<main>
  {% if is_full_page_list %}
    <div class="full-page-grid-container">
      <h2 class="full-page-grid-title">{{ list_title }}</h2>
      {% if contents|length == 0 %}<p style="text-align:center; color: var(--text-dark); margin-top: 40px;">No content found.</p>
      {% else %}<div class="full-page-grid">{% for m in contents %}{{ render_movie_card(m) }}{% endfor %}</div>{% endif %}
    </div>
  {% else %}
    {% if recently_added %}
      <div class="hero-section">
        {% for content in recently_added %}
          <div class="hero-slide {% if loop.first %}active{% endif %}" style="background-image: url('{{ content.poster_url or '' }}');">
            <div class="hero-content">
              <h1 class="hero-title">{{ content.title }}</h1>
              <p class="hero-overview">{{ content.description }}</p>
              <div class="hero-buttons">
                 <a href="{{ url_for('content_detail', content_id=content._id) }}" class="btn btn-primary"><i class="fas fa-play"></i> View Details</a>
              </div>
            </div>
          </div>
        {% endfor %}
      </div>
    {% endif %}
    {% if all_content %}
      <div class="full-page-grid-container" style="padding-top: 40px;">
        <h2 class="full-page-grid-title">All Movies & Series</h2>
        <div class="full-page-grid">{% for m in all_content %}{{ render_movie_card(m) }}{% endfor %}</div>
      </div>
    {% endif %}
  {% endif %}
</main>
<nav class="bottom-nav">
  <a href="{{ url_for('home') }}" class="nav-item active"><i class="fas fa-home"></i><span>Home</span></a>
  <a href="{{ url_for('admin') if session.get('logged_in') else url_for('admin_login_page') }}" class="nav-item"><i class="fas fa-user-shield"></i><span>Admin</span></a>
</nav>
<script>
    const nav = document.querySelector('.main-nav');
    if(nav) window.addEventListener('scroll', () => { window.scrollY > 50 ? nav.classList.add('scrolled') : nav.classList.remove('scrolled'); });
    document.addEventListener('DOMContentLoaded', function() {
        const slides = document.querySelectorAll('.hero-slide');
        if (slides.length > 1) {
            let currentSlide = 0;
            const showSlide = (index) => slides.forEach((s, i) => s.classList.toggle('active', i === index));
            setInterval(() => { currentSlide = (currentSlide + 1) % slides.length; showSlide(currentSlide); }, 5000);
        }
    });
</script>
</body>
</html>
"""

DETAIL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
<title>{{ content.title if content else "Not Found" }} - MovieZone</title>
<style>{{ css_code|safe }}</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
<header class="detail-header"><a href="{{ url_for('home') }}" class="back-button"><i class="fas fa-arrow-left"></i> Back to Home</a></header>
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
      </div>
      <p class="detail-overview">{{ content.description }}</p>
      <div class="download-section">
        <h3 class="section-title">Get from Bot</h3>
        <div class="quality-buttons">
          {% if content.qualities %}
            {% for quality, msg_id in content.qualities.items() %}
              <a href="https://t.me/{{ bot_username }}?start=get_{{ content._id }}_{{ quality }}" class="watch-now-btn" target="_blank">
                <i class="fas fa-robot"></i> Get {{ quality }}
              </a>
            {% endfor %}
          {% else %}<p>No download links available from bot.</p>
          {% endif %}
        </div>
      </div>
    </div>
  </div>
</div>
{% else %}<div style="display:flex; justify-content:center; align-items:center; height:100vh;"><h2>Content not found.</h2></div>
{% endif %}
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Admin Panel - MovieZone</title><meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>{{ css_code|safe }}{{ admin_css|safe }}</style>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;700&display=swap" rel="stylesheet">
</head>
<body>
  <header class="main-nav"><a href="{{ url_for('home') }}" class="logo">MovieZone</a>
  {% if session.get('logged_in') %}<a href="{{ url_for('admin_logout') }}" class="btn-logout">Logout</a>{% endif %}</header>
  <div class="admin-wrapper">
    {% block content %}{% endblock %}
  </div>
</body>
</html>
"""

ADMIN_LOGIN_HTML = """
{% extends "admin_base" %}
{% block content %}
<h2>Admin Login</h2>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for category, message in messages %}<div class="flash-msg {{category}}">{{ message }}</div>{% endfor %}{% endif %}
{% endwith %}
<form method="post" class="admin-form">
    <div class="form-group"><label for="username">Username</label><input type="text" name="username" required></div>
    <div class="form-group"><label for="password">Password</label><input type="password" name="password" required></div>
    <button type="submit">Login</button>
</form>
{% endblock %}
"""

ADMIN_DASHBOARD_HTML = """
{% extends "admin_base" %}
{% block content %}
<h2>Admin Dashboard</h2>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}{% for category, message in messages %}<div class="flash-msg {{category}}">{{ message }}</div>{% endfor %}{% endif %}
{% endwith %}
<hr class="section-divider">
<h3>Add/Update Content (Manual)</h3>
<form method="post" action="{{ url_for('admin_add_content') }}" class="admin-form">
    <div class="form-group"><label>Title (e.g., Jawan or Mirzapur S01E01):</label><input type="text" name="title" required /></div>
    <div class="form-group"><label>Quality (e.g., 720p):</label><input type="text" name="quality" required /></div>
    <div class="form-group"><label>Telegram Message ID:</label><input type="text" name="message_id" required /></div>
    <p>Leave details below blank to auto-fetch from TMDb.</p>
    <div class="form-group"><label>Poster URL:</label><input type="url" name="poster_url" /></div>
    <div class="form-group"><label>Description:</label><textarea name="overview"></textarea></div>
    <button type="submit">Add/Update Content</button>
</form>
<hr class="section-divider">
<h3>Manage Content</h3>
<div class="table-responsive">
    <table class="content-table">
        <thead><tr><th>Poster</th><th>Title</th><th>Qualities</th><th>Actions</th></tr></thead>
        <tbody>
        {% for content in all_content %}
        <tr>
            <td><img src="{{ content.poster_url or 'https://via.placeholder.com/50x75' }}" alt="poster" width="40"></td>
            <td>{{ content.title }}</td>
            <td>
                {% if content.qualities %}
                    {% for quality in content.qualities.keys() %}<span class="type-badge">{{ quality }}</span>{% endfor %}
                {% else %}N/A{% endif %}
            </td>
            <td class="action-buttons">
                <a href="{{ url_for('admin_edit', content_id=content._id) }}" class="edit-btn">Edit</a>
                <a href="{{ url_for('admin_delete', content_id=content._id) }}" class="delete-btn" onclick="return confirm('Are you sure?');">Delete</a>
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
"""

ADMIN_EDIT_HTML = """
{% extends "admin_base" %}
{% block content %}
<h2>Edit: {{ content.title }}</h2>
<form method="post" class="admin-form">
    <div class="form-group"><label for="title">Title</label><input type="text" name="title" value="{{ content.title }}" required></div>
    <div class="form-group"><label for="description">Description</label><textarea name="description" rows="5">{{ content.description }}</textarea></div>
    <div class="form-group"><label for="poster_url">Poster URL</label><input type="url" name="poster_url" value="{{ content.poster_url }}"></div>
    <button type="submit">Save Changes</button>
    <a href="{{ url_for('admin_dashboard') }}" class="cancel-link">Cancel</a>
</form>
{% endblock %}
"""


CSS_CODE = """
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
:root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; --text-dark: #a0a0a0; --nav-height: 60px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Roboto', sans-serif; background-color: var(--netflix-black); color: var(--text-light); overflow-x: hidden; }
a { text-decoration: none; color: inherit; }
.main-nav { position: fixed; top: 0; left: 0; width: 100%; padding: 15px 50px; display: flex; justify-content: space-between; align-items: center; z-index: 100; transition: background-color 0.3s ease; background: linear-gradient(to bottom, rgba(0,0,0,0.8) 10%, rgba(0,0,0,0)); }
.main-nav.scrolled { background-color: var(--netflix-black); }
.logo { font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: var(--netflix-red); font-weight: 700; letter-spacing: 1px; }
.search-input { background-color: rgba(0,0,0,0.7); border: 1px solid #777; color: var(--text-light); padding: 8px 15px; border-radius: 4px; width: 250px; }
.hero-section { height: 85vh; position: relative; color: white; overflow: hidden; }
.hero-slide { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background-size: cover; background-position: center top; display: flex; align-items: flex-end; padding: 50px; opacity: 0; transition: opacity 1.5s ease-in-out; z-index: 1; }
.hero-slide.active { opacity: 1; z-index: 2; }
.hero-slide::before { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, var(--netflix-black) 10%, transparent 50%), linear-gradient(to right, rgba(0,0,0,0.8) 0%, transparent 60%); }
.hero-content { position: relative; z-index: 3; max-width: 50%; }
.hero-title { font-family: 'Bebas Neue', sans-serif; font-size: 5rem; line-height: 1; }
.hero-overview { font-size: 1.1rem; line-height: 1.5; margin: 1rem 0; max-width: 600px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.hero-buttons .btn { padding: 8px 20px; border-radius: 4px; font-weight: 700; }
.btn.btn-primary { background-color: var(--netflix-red); color: white; }
.full-page-grid-container { padding: 100px 50px 50px 50px; }
.full-page-grid-title { font-size: 2.5rem; font-weight: 700; margin-bottom: 30px; }
.full-page-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; }
.movie-card { min-width: 0; border-radius: 4px; overflow: hidden; cursor: pointer; transition: transform 0.3s ease; position: relative; background-color: #222; display: block; }
.movie-poster { width: 100%; aspect-ratio: 2 / 3; object-fit: cover; display: block; }
.card-info-overlay { position: absolute; bottom: 0; left: 0; right: 0; padding: 20px 10px 10px 10px; background: linear-gradient(to top, rgba(0,0,0,0.95) 20%, transparent 100%); color: white; text-align: center; opacity: 0; transform: translateY(20px); transition: opacity 0.3s ease; z-index: 2; }
.card-info-title { font-size: 1rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (hover: hover) { .movie-card:hover { transform: scale(1.05); z-index: 5; } .movie-card:hover .card-info-overlay { opacity: 1; transform: translateY(0); } }
.bottom-nav { display: none; }
.detail-header { position: absolute; top: 0; left: 0; right: 0; padding: 20px 50px; z-index: 100; }
.back-button { color: var(--text-light); font-size: 1.2rem; font-weight: 700; }
.detail-hero { position: relative; width: 100%; display: flex; align-items: center; justify-content: center; padding: 100px 0; }
.detail-hero-background { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background-size: cover; background-position: center; filter: blur(20px) brightness(0.4); transform: scale(1.1); }
.detail-hero::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, rgba(20,20,20,1) 0%, rgba(20,20,20,0.6) 50%, rgba(20,20,20,1) 100%); }
.detail-content-wrapper { position: relative; z-index: 2; display: flex; gap: 40px; max-width: 1200px; padding: 0 50px; width: 100%; }
.detail-poster { width: 300px; height: 450px; flex-shrink: 0; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); object-fit: cover; }
.detail-info { flex-grow: 1; max-width: 65%; }
.detail-title { font-family: 'Bebas Neue', sans-serif; font-size: 4.5rem; line-height: 1.1; }
.detail-meta { display: flex; flex-wrap: wrap; gap: 20px; margin: 20px 0 25px 0; }
.detail-overview { line-height: 1.6; margin-bottom: 30px; }
.quality-buttons a.watch-now-btn { display: inline-block; margin-right: 10px; margin-bottom: 10px; }
.watch-now-btn { background-color: var(--netflix-red); color: white; padding: 12px 25px; font-size: 1rem; font-weight: 700; border-radius: 5px; }
@media (max-width: 768px) { body { padding-bottom: var(--nav-height); } .main-nav { padding: 10px 15px; } .logo { font-size: 24px; } .full-page-grid-container { padding: 80px 15px 30px; } .full-page-grid-title { font-size: 1.8rem; } .full-page-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); } .bottom-nav { display: flex; } .detail-content-wrapper { flex-direction: column; align-items: center; text-align: center; } .detail-info { max-width: 100%; } .detail-title { font-size: 3.5rem; } .detail-poster { width: 60%; max-width: 220px; height: auto; } }
"""

ADMIN_CSS = """
.admin-wrapper { padding: 100px 20px 40px; max-width: 900px; margin: 0 auto; }
.admin-wrapper h2 { font-family: 'Bebas Neue', sans-serif; color: var(--netflix-red); font-size: 2.5rem; margin-bottom: 20px; }
.admin-wrapper h3 { font-family: 'Bebas Neue', sans-serif; color: #fff; font-size: 1.5rem; margin: 20px 0 10px 0; }
.admin-form { background: #222; padding: 25px; border-radius: 8px; margin-top: 20px; }
.form-group { margin-bottom: 15px; } .form-group label { display: block; margin-bottom: 8px; font-weight: bold; }
input[type="text"], input[type="url"], input[type="password"], textarea { width: 100%; padding: 12px; border-radius: 4px; border: 1px solid #333; font-size: 1rem; background: #333; color: var(--text-light); }
.admin-form button { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1rem; width: 100%; }
.flash-msg { padding: 1rem; margin-bottom: 1rem; border-radius: 4px; } .flash-msg.success { background-color: #1f4e2c; color: #d4edda; } .flash-msg.error { background-color: #721c24; color: #f8d7da; }
.table-responsive { overflow-x: auto; } .content-table { width: 100%; border-collapse: collapse; }
.content-table th, .content-table td { padding: 12px; text-align: left; border-bottom: 1px solid #333; white-space: nowrap; }
.content-table th { background: #252525; } .action-buttons { display: flex; gap: 10px; }
.action-buttons a { padding: 6px 12px; border-radius: 4px; text-decoration: none; color: white; }
.edit-btn { background: #0d6efd; } .delete-btn { background: #dc3545; }
.type-badge { background-color: #0dcaf0; color: #000; padding: 0.25em 0.5em; border-radius: 0.25rem; font-size: .8em; font-weight: 700; text-transform: uppercase; margin-right: 5px; }
.cancel-link { display: inline-block; margin-top: 10px; color: var(--text-dark); }
.btn-logout { color:white; border: 1px solid white; padding: 5px 10px; border-radius: 4px; }
.section-divider { border: 0; height: 1px; background-color: #333; margin: 40px 0; }
"""

# === Jinja2 এর জন্য সঠিক লোডার এবং রেন্ডারার (ফিক্সড) ===
jinja_env = Environment(
    loader=BaseLoader(),
    extensions=['jinja2.ext.do']
)

@app.context_processor
def inject_global_vars():
    return dict(bot_username=BOT_USERNAME, session=session)

def render(template_string, **context):
    return render_template_string(template_string, **context)

# --- অ্যাডমিন লগইন ডেকোরেটর ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

def parse_filename(filename):
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    quality_match = re.search(r'(\d{3,4}p)', cleaned_name, re.IGNORECASE)
    quality = quality_match.group(1).lower() if quality_match else 'HD'
    series_match = re.search(r'^(.*?)[\s\._-]*[sS](\d+)[eE](\d+)', cleaned_name, re.IGNORECASE)
    if series_match: return {'type': 'tv', 'title': series_match.group(1).strip(), 'season': int(series_match.group(2)), 'episode': int(series_match.group(3)), 'quality': quality}
    movie_match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name, re.IGNORECASE)
    if movie_match: return {'type': 'movie', 'title': movie_match.group(1).strip(), 'year': movie_match.group(2).strip(), 'quality': quality}
    return None

def get_tmdb_details(parsed_info):
    api_url = f"https://api.themoviedb.org/3/search/{parsed_info['type']}"
    params = {'api_key': TMDB_API_KEY, 'query': parsed_info['title']}
    if parsed_info['type'] == 'movie': params['primary_release_year'] = parsed_info.get('year')
    try:
        r = requests.get(api_url, params=params)
        r.raise_for_status(); res = r.json()
        if res.get('results'):
            data = res['results'][0]
            if parsed_info['type'] == 'movie': title = data.get('title')
            else: title = f"{data.get('name')} S{parsed_info['season']:02d}E{parsed_info['episode']:02d}"
            return {'title': title, 'original_title': data.get('original_title') or data.get('original_name'), 'description': data.get('overview'), 'poster_url': f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else None, 'release_year': (data.get('release_date') or data.get('first_air_date', ''))[:4], 'rating': round(data.get('vote_average', 0), 1)}
    except requests.exceptions.RequestException as e: print(f"Error fetching TMDb info: {e}")
    return None

# --- সাধারণ ব্যবহারকারীর রাউট ---
@app.route('/')
def home():
    if content_collection is None: return "Database connection failed.", 500
    query = request.args.get('q')
    if query:
        contents = list(content_collection.find({"title": {"$regex": query, "$options": "i"}}).sort('_id', -1))
        return render(INDEX_HTML, contents=contents, css_code=CSS_CODE, is_full_page_list=True, list_title=f'Results for "{query}"', query=query)
    
    recently_added = list(content_collection.find().sort('_id', -1).limit(5))
    all_content = list(content_collection.find().sort('_id', -1).limit(18))
    
    # render_movie_card ম্যাক্রোকে একটি ভেরিয়েবলে রেখে পাস করা হচ্ছে
    card_macro = """
    {% macro render_movie_card(m) %}
        <a href="{{ url_for('content_detail', content_id=m._id) }}" class="movie-card">
          <img class="movie-poster" loading="lazy" src="{{ m.poster_url or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ m.title }}">
          <div class="card-info-overlay"><h4 class="card-info-title">{{ m.title }}</h4></div>
        </a>
    {% endmacro %}
    """
    return render(card_macro + INDEX_HTML, all_content=all_content, recently_added=recently_added, css_code=CSS_CODE, is_full_page_list=False)

@app.route('/content/<content_id>')
def content_detail(content_id):
    if content_collection is None: return "Database connection failed.", 500
    try:
        content = content_collection.find_one({'_id': ObjectId(content_id)})
        return render(DETAIL_HTML, content=content, css_code=CSS_CODE) if content else abort(404)
    except: abort(404)

# --- অ্যাডমিন প্যানেলের রাউট ---
@app.route('/admin', methods=['GET'])
@login_required
def admin_dashboard():
    all_content = list(content_collection.find().sort('_id', -1))
    return render(ADMIN_DASHBOARD_HTML, contents=all_content, css_code=CSS_CODE+ADMIN_CSS)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login_page():
    if session.get('logged_in'): return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USER and request.form['password'] == ADMIN_PASS:
            session['logged_in'] = True; return redirect(url_for('admin_dashboard'))
        else: flash('Invalid credentials.', 'error')
    return render(ADMIN_LOGIN_HTML, css_code=CSS_CODE+ADMIN_CSS)

@app.route('/admin/add', methods=['POST'])
@login_required
def admin_add_content():
    filename = request.form.get('title')
    quality = request.form.get('quality')
    message_id = request.form.get('message_id')
    
    if filename and quality and message_id:
        process_telegram_post(filename, int(message_id), quality)
    
    flash('Content added/updated successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit/<content_id>', methods=['GET', 'POST'])
@login_required
def admin_edit(content_id):
    content = content_collection.find_one({'_id': ObjectId(content_id)})
    if request.method == 'POST':
        updated_data = {'title': request.form['title'], 'description': request.form['description'], 'poster_url': request.form['poster_url']}
        content_collection.update_one({'_id': ObjectId(content_id)}, {'$set': updated_data})
        flash('Content updated successfully!', 'success'); return redirect(url_for('admin_dashboard'))
    return render(ADMIN_EDIT_HTML, content=content, css_code=CSS_CODE+ADMIN_CSS)

@app.route('/admin/delete/<content_id>')
@login_required
def admin_delete(content_id):
    content_collection.delete_one({'_id': ObjectId(content_id)})
    flash('Content deleted successfully!', 'success'); return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None); return redirect(url_for('admin_login_page'))

def process_telegram_post(filename, message_id, quality_override=None):
    parsed_info = parse_filename(filename)
    if not parsed_info: return
    
    quality = quality_override or parsed_info['quality']
    
    # এখানে সিরিজের নাম থেকে সিজন/এপিসোড নম্বর বাদ দেওয়া হচ্ছে যাতে মূল টাইটেল দিয়ে সার্চ করা যায়
    search_title = parsed_info['title']
    if parsed_info['type'] == 'tv':
        search_title = re.sub(r'\s*[sS]\d+[eE]\d+.*', '', search_title, flags=re.IGNORECASE).strip()

    existing_content = content_collection.find_one({'original_title': search_title})
    
    if existing_content:
        quality_key = f"qualities.{quality}"
        content_collection.update_one({'_id': existing_content['_id']}, {'$set': {quality_key: message_id}})
        print(f"SUCCESS: Updated quality '{quality}' for '{existing_content['title']}'")
    else:
        tmdb_data = get_tmdb_details(parsed_info)
        if tmdb_data:
            tmdb_data['qualities'] = {quality: message_id}
            content_collection.insert_one(tmdb_data)
            print(f"SUCCESS: New content '{tmdb_data['title']}' saved.")

# --- টেলিগ্রাম ওয়েবহুক ---
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        if str(post['chat']['id']) == ADMIN_CHANNEL_ID:
            file = post.get('video') or post.get('document')
            if file: process_telegram_post(file.get('file_name', ''), post['message_id'])
    elif 'message' in data:
        message = data['message']
        chat_id, text = message['chat']['id'], message.get('text', '')
        if text == '/start':
            requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Welcome! Please browse our website.")
        elif text.startswith('/start get_'):
            try:
                parts = text.split('_'); content_id_str, quality = parts[1], parts[2]
                content = content_collection.find_one({'_id': ObjectId(content_id_str)})
                if content and quality in content.get('qualities', {}):
                    message_id = content['qualities'][quality]
                    payload = {'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': message_id}
                    requests.post(f"{TELEGRAM_API_URL}/copyMessage", json=payload)
                else: requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, content or quality not found.")
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=An unexpected error occurred.")
    return jsonify(status='ok')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
