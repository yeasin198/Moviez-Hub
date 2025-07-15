import os
import sys
import re
import requests
import boto3
from flask import Flask, render_template_string, request, redirect, url_for, Response, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
from functools import wraps
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Thread
from werkzeug.utils import secure_filename

# ======================================================================
# --- এনভায়রনমেন্ট ভেরিয়েবল লোড এবং ভ্যালিডেশন ---
# ======================================================================
MONGO_URI = os.environ.get("MONGO_URI")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
B2_KEY_ID = os.environ.get("B2_KEY_ID")
B2_APPLICATION_KEY = os.environ.get("B2_APPLICATION_KEY")
B2_ENDPOINT_URL = os.environ.get("B2_ENDPOINT_URL")
B2_BUCKET_NAME = os.environ.get("B2_BUCKET_NAME")

required_vars = { "MONGO_URI": MONGO_URI, "BOT_TOKEN": BOT_TOKEN, "TMDB_API_KEY": TMDB_API_KEY, "ADMIN_CHANNEL_ID": ADMIN_CHANNEL_ID, "BOT_USERNAME": BOT_USERNAME, "ADMIN_USERNAME": ADMIN_USERNAME, "ADMIN_PASSWORD": ADMIN_PASSWORD, }
missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    print(f"FATAL: Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

# ======================================================================
# --- অ্যাপ্লিকেশন এবং ক্লায়েন্ট সেটআপ ---
# ======================================================================
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)

# --- অ্যাডমিন অথেন্টিকেশন ---
def check_auth(username, password): return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
def authenticate(): return Response('Could not verify your access level.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password): return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- ডাটাবেস ও S3 ক্লায়েন্ট ---
try:
    client = MongoClient(MONGO_URI)
    db = client["movie_db"]
    movies = db["movies"]
    settings = db["settings"]
    feedback = db["feedback"]
    print("SUCCESS: Successfully connected to MongoDB!")
except Exception as e:
    print(f"FATAL: Error connecting to MongoDB: {e}. Exiting.")
    sys.exit(1)

s3_client = None
if all([B2_KEY_ID, B2_APPLICATION_KEY, B2_ENDPOINT_URL, B2_BUCKET_NAME]):
    try:
        s3_client = boto3.client('s3', endpoint_url=B2_ENDPOINT_URL, aws_access_key_id=B2_KEY_ID, aws_secret_access_key=B2_APPLICATION_KEY)
        print("SUCCESS: B2/S3 client initialized.")
    except Exception as e:
        print(f"ERROR: Could not initialize B2/S3 client. Error: {e}")
else:
    print("WARNING: B2/S3 credentials not fully set in environment variables. File upload from Telegram will be disabled.")

# --- সিডিউলার সেটআপ ---
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

# --- Context Processor ---
@app.context_processor
def inject_ads():
    ad_codes = settings.find_one()
    return dict(ad_settings=(ad_codes or {}), bot_username=BOT_USERNAME)

# ======================================================================
# --- HTML টেমপ্লেট (সম্পূর্ণ এবং আপডেট করা) ---
# ======================================================================
index_html = """
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" /><title>MovieZone - Your Entertainment Hub</title><style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
:root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; --text-dark: #a0a0a0; --nav-height: 60px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Roboto', sans-serif; background-color: var(--netflix-black); color: var(--text-light); overflow-x: hidden; } a { text-decoration: none; color: inherit; }
::-webkit-scrollbar { width: 8px; } ::-webkit-scrollbar-track { background: #222; } ::-webkit-scrollbar-thumb { background: #555; } ::-webkit-scrollbar-thumb:hover { background: var(--netflix-red); }
.main-nav { position: fixed; top: 0; left: 0; width: 100%; padding: 15px 50px; display: flex; justify-content: space-between; align-items: center; z-index: 100; transition: background-color 0.3s ease; background: linear-gradient(to bottom, rgba(0,0,0,0.8) 10%, rgba(0,0,0,0)); }
.main-nav.scrolled { background-color: rgba(20, 20, 20, 0.8); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); }
.logo { font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: var(--netflix-red); font-weight: 700; letter-spacing: 1px; }
.search-input { background-color: rgba(0,0,0,0.7); border: 1px solid #777; color: var(--text-light); padding: 8px 15px; border-radius: 4px; transition: width 0.3s ease, background-color 0.3s ease; width: 250px; }
.search-input:focus { background-color: rgba(0,0,0,0.9); border-color: var(--text-light); outline: none; }
.hero-section { height: 85vh; position: relative; color: white; overflow: hidden; }
.hero-slide { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background-size: cover; background-position: center top; display: flex; align-items: flex-end; padding: 50px; opacity: 0; transition: opacity 1.5s ease-in-out; z-index: 1; }
.hero-slide.active { opacity: 1; z-index: 2; }
.hero-slide::before { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, var(--netflix-black) 10%, transparent 50%), linear-gradient(to right, rgba(0,0,0,0.8) 0%, transparent 60%); }
.hero-content { position: relative; z-index: 3; max-width: 50%; }
.hero-title { font-family: 'Bebas Neue', sans-serif; font-size: 5rem; font-weight: 700; margin-bottom: 1rem; line-height: 1; }
.hero-overview { font-size: 1.1rem; line-height: 1.5; margin-bottom: 1.5rem; max-width: 600px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.hero-buttons .btn { padding: 12px 24px; margin-right: 0.8rem; border: none; border-radius: 4px; font-size: 1rem; font-weight: 700; cursor: pointer; transition: opacity 0.3s ease; display: inline-flex; align-items: center; gap: 8px; }
.btn.btn-primary { background-color: var(--netflix-red); color: white; } .btn.btn-secondary { background-color: rgba(109, 109, 110, 0.7); color: white; } .btn:hover { opacity: 0.8; }
main { padding: 40px 50px; }
.movie-card { display: block; cursor: pointer; transition: transform 0.3s ease; background-color: #1a1a1a; border-radius: 6px; overflow: hidden; }
.movie-poster-container { position: relative; overflow: hidden; width:100%; aspect-ratio: 2 / 3; }
.movie-poster { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.4s ease; }
.poster-badge { position: absolute; top: 10px; left: 10px; background-color: var(--netflix-red); color: white; padding: 4px 8px; font-size: 0.7rem; font-weight: 700; border-radius: 4px; z-index: 3; box-shadow: 0 2px 5px rgba(0,0,0,0.5); }
.rating-badge { position: absolute; top: 10px; right: 10px; background-color: rgba(0, 0, 0, 0.8); color: white; padding: 5px 10px; font-size: 0.8rem; font-weight: 700; border-radius: 20px; z-index: 3; display: flex; align-items: center; gap: 5px; backdrop-filter: blur(5px); }
.rating-badge .fa-star { color: #f5c518; }
.card-info-static { padding: 10px 12px; }
.card-info-title { font-size: 0.9rem; font-weight: 500; color: var(--text-light); margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-info-meta { font-size: 0.75rem; color: var(--text-dark); margin: 0; }
@media (hover: hover) { .movie-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 0 20px rgba(229, 9, 20, 0.5); } .movie-card:hover .movie-poster { transform: scale(1.1); } }
.full-page-grid-container { padding-top: 100px; padding-bottom: 50px; }
.full-page-grid-title { font-size: 2.5rem; font-weight: 700; margin-bottom: 30px; }
.category-grid, .full-page-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px 15px; }
.category-section { margin: 40px 0; opacity: 0; transform: translateY(30px); transition: opacity 0.6s ease-out, transform 0.6s ease-out; }
.category-section.visible { opacity: 1; transform: translateY(0); }
.category-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.category-title { font-family: 'Roboto', sans-serif; font-weight: 700; font-size: 1.8rem; margin: 0; }
.see-all-link { color: var(--text-dark); font-weight: 700; font-size: 0.9rem; }
.bottom-nav { display: none; position: fixed; bottom: 0; left: 0; right: 0; height: var(--nav-height); background-color: #181818; border-top: 1px solid #282828; justify-content: space-around; align-items: center; z-index: 200; }
.nav-item { display: flex; flex-direction: column; align-items: center; color: var(--text-dark); font-size: 10px; flex-grow: 1; padding: 5px 0; transition: color 0.2s ease; }
.nav-item i { font-size: 20px; margin-bottom: 4px; } .nav-item.active { color: var(--text-light); } .nav-item.active i { color: var(--netflix-red); }
.ad-container { margin: 40px 0; display: flex; justify-content: center; align-items: center; }
.telegram-join-section { background-color: #181818; padding: 40px 20px; text-align: center; margin: 50px -50px -50px -50px; }
.telegram-join-section h2 { font-family: 'Bebas Neue', sans-serif; font-size: 2.5rem; margin-bottom: 10px; }
@media (max-width: 768px) {
    body { padding-bottom: var(--nav-height); } main { padding: 20px 15px; } .logo { font-size: 24px; } .search-input { width: 150px; }
    .hero-section { height: 60vh; margin: 0 -15px;} .hero-content { max-width: 90%; } .hero-title { font-size: 2.8rem; } .hero-overview { display: none; }
    .category-section { margin: 25px 0; } .category-title { font-size: 1.4rem; }
    .category-grid, .full-page-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 15px 10px; }
    .full-page-grid-container { padding-top: 80px; } .full-page-grid-title { font-size: 1.8rem; }
    .bottom-nav { display: flex; } .telegram-join-section { margin: 50px -15px -30px -15px; }
}
</style><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css"></head>
<body>
<header class="main-nav"><a href="{{ url_for('home') }}" class="logo">MovieZone</a><form method="GET" action="/" class="search-form"><input type="search" name="q" class="search-input" placeholder="Search..." value="{{ query|default('') }}" /></form></header>
<main>
  {% macro render_movie_card(m) %}
    <a href="{{ url_for('movie_detail', movie_id=m._id) }}" class="movie-card">
      <div class="movie-poster-container">
        <img class="movie-poster" loading="lazy" src="{{ m.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ m.title }}">
        {% if m.poster_badge %}<div class="poster-badge">{{ m.poster_badge }}</div>{% endif %}
        {% if m.vote_average and m.vote_average > 0 %}<div class="rating-badge"><i class="fas fa-star"></i> {{ "%.1f"|format(m.vote_average) }}</div>{% endif %}
      </div>
      <div class="card-info-static">
        <h4 class="card-info-title">{{ m.title }}</h4>
        {% if m.release_date %}<p class="card-info-meta">{{ m.release_date.split('-')[0] }}</p>{% endif %}
      </div>
    </a>
  {% endmacro %}
  {% if is_full_page_list %}
    <div class="full-page-grid-container"><h2 class="full-page-grid-title">{{ query }}</h2>
      <div class="full-page-grid">{% for m in movies %}{{ render_movie_card(m) }}{% else %}<p>No content found.</p>{% endfor %}</div>
    </div>
  {% else %}
    {% if recently_added %}<div class="hero-section">{% for movie in recently_added %}<div class="hero-slide {% if loop.first %}active{% endif %}" style="background-image: url('{{ movie.poster or '' }}');"><div class="hero-content"><h1 class="hero-title">{{ movie.title }}</h1><p class="hero-overview">{{ movie.overview }}</p><div class="hero-buttons">{% if movie.watch_link %}<a href="{{ movie.watch_link }}" target="_blank" class="btn btn-primary"><i class="fas fa-play"></i> Watch Now</a>{% endif %}<a href="{{ url_for('movie_detail', movie_id=movie._id) }}" class="btn btn-secondary"><i class="fas fa-info-circle"></i> More Info</a></div></div></div>{% endfor %}</div>{% endif %}
    {% macro render_grid_section(title, movies_list, endpoint) %}
      {% if movies_list %}<div class="category-section"><div class="category-header"><h2 class="category-title">{{ title }}</h2><a href="{{ url_for(endpoint) }}" class="see-all-link">See All ></a></div><div class="category-grid">{% for m in movies_list %}{{ render_movie_card(m) }}{% endfor %}</div></div>{% endif %}
    {% endmacro %}
    {{ render_grid_section('Trending Now', trending_movies, 'trending_movies') }}
    {% if ad_settings.banner_ad_code %}<div class="ad-container">{{ ad_settings.banner_ad_code|safe }}</div>{% endif %}
    {{ render_grid_section('Latest Movies', latest_movies, 'movies_only') }}
    {% if ad_settings.native_banner_code %}<div class="ad-container">{{ ad_settings.native_banner_code|safe }}</div>{% endif %}
    {{ render_grid_section('Web Series', latest_series, 'webseries') }}
    {{ render_grid_section('Recently Added', recently_added_full, 'recently_added_all') }}
    {{ render_grid_section('Coming Soon', coming_soon_movies, 'coming_soon') }}
    <div class="telegram-join-section"><h2>Join Our Telegram Channel</h2><p>Get the latest movie updates and direct download links!</p><a href="https://t.me/your_channel_username" target="_blank" class="btn btn-primary" style="background-color: #2AABEE;"><i class="fab fa-telegram-plane"></i> Join Now</a></div>
  {% endif %}
</main>
<nav class="bottom-nav"><a href="{{ url_for('home') }}" class="nav-item active"><i class="fas fa-home"></i><span>Home</span></a><a href="{{ url_for('genres_page') }}" class="nav-item"><i class="fas fa-layer-group"></i><span>Genres</span></a><a href="{{ url_for('contact') }}" class="nav-item"><i class="fas fa-envelope"></i><span>Request</span></a></nav>
<script>
const nav = document.querySelector('.main-nav'); window.addEventListener('scroll', () => { window.scrollY > 50 ? nav.classList.add('scrolled') : nav.classList.remove('scrolled'); });
document.addEventListener('DOMContentLoaded', () => {
  const slides = document.querySelectorAll('.hero-slide'); if (slides.length > 1) { let current = 0; setInterval(() => { slides.forEach((s, i) => s.classList.toggle('active', i === current)); current = (current + 1) % slides.length; }, 5000); }
  const observer = new IntersectionObserver((e) => { e.forEach(entry => { if(entry.isIntersecting) entry.target.classList.add('visible'); }); }, { threshold: 0.1 });
  document.querySelectorAll('.category-section').forEach(s => observer.observe(s));
});
</script>
{% if ad_settings.popunder_code %}{{ ad_settings.popunder_code|safe }}{% endif %}
</body></html>
"""
detail_html = """
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" /><title>{{ movie.title if movie else "Not Found" }} - MovieZone</title><style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
:root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; --text-dark: #a0a0a0; }
body { font-family: 'Roboto', sans-serif; background: var(--netflix-black); color: var(--text-light); }
.detail-header { position: absolute; top: 0; left: 0; right: 0; padding: 20px 50px; z-index: 100; }
.back-button { color: var(--text-light); font-size: 1.2rem; text-decoration: none; display:flex; align-items:center; gap: 8px; }
.detail-hero { position: relative; width: 100%; display: flex; align-items: center; justify-content: center; padding: 120px 50px 60px; }
.detail-hero-background { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background-size: cover; background-position: center; filter: blur(20px) brightness(0.4); transform: scale(1.1); }
.detail-hero::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, rgba(20,20,20,1) 0%, rgba(20,20,20,0.6) 50%, rgba(20,20,20,1) 100%); }
.detail-content-wrapper { position: relative; z-index: 2; display: flex; gap: 40px; max-width: 1200px; width: 100%; }
.detail-poster { width: 300px; height: 450px; flex-shrink: 0; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); object-fit: cover; }
.detail-info { flex-grow: 1; } .detail-title { font-family: 'Bebas Neue', sans-serif; font-size: 4.5rem; line-height: 1.1; margin-bottom: 20px; }
.detail-meta { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 25px; color: var(--text-dark); }
.detail-meta span { font-weight: 700; color: var(--text-light); } .detail-meta span i { margin-right: 5px; color: var(--text-dark); }
.detail-overview { font-size: 1.1rem; line-height: 1.6; margin-bottom: 30px; }
.action-btn { background-color: var(--netflix-red); color: white; padding: 15px 30px; font-size: 1.2rem; font-weight: 700; border: none; border-radius: 5px; cursor: pointer; display: inline-flex; align-items: center; gap: 10px; text-decoration: none; margin: 0 10px 15px 0; }
.section-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; padding-bottom: 5px; border-bottom: 2px solid var(--netflix-red); display: inline-block; }
.video-container { position: relative; padding-bottom: 56.25%; height: 0; border-radius: 8px; overflow:hidden; } .video-container iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
.ad-container { margin: 30px 0; text-align: center; }
.related-section-container { padding: 40px 50px; background-color: #181818; }
.related-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px 15px; }
.movie-card { display: block; background-color: #1a1a1a; border-radius: 6px; overflow: hidden; }
.movie-poster-container { aspect-ratio: 2/3; } .movie-poster { width: 100%; height: 100%; object-fit: cover; }
.card-info-static { padding: 10px 12px; } .card-info-title { font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 992px) { .detail-content-wrapper { flex-direction: column; align-items: center; text-align: center; } }
@media (max-width: 768px) { .detail-hero { padding: 100px 20px 40px; } .detail-poster { width: 60%; max-width: 220px; height: auto; } .detail-title { font-size: 2.5rem; } .related-section-container { padding: 20px 15px; } .related-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 15px 10px; } }
</style><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css"></head>
<body>
{% macro render_movie_card(m) %}
  <a href="{{ url_for('movie_detail', movie_id=m._id) }}" class="movie-card">
    <div class="movie-poster-container"><img class="movie-poster" loading="lazy" src="{{ m.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ m.title }}"></div>
    <div class="card-info-static"><h4 class="card-info-title">{{ m.title }}</h4></div>
  </a>
{% endmacro %}
<header class="detail-header"><a href="{{ url_for('home') }}" class="back-button"><i class="fas fa-arrow-left"></i> Back to Home</a></header>
{% if movie %}
<div class="detail-hero"><div class="detail-hero-background" style="background-image: url('{{ movie.poster }}');"></div>
  <div class="detail-content-wrapper"><img class="detail-poster" src="{{ movie.poster }}" alt="{{ movie.title }}">
    <div class="detail-info">
      <h1 class="detail-title">{{ movie.title }}</h1>
      <div class="detail-meta">
        {% if movie.release_date %}<span>{{ movie.release_date.split('-')[0] }}</span>{% endif %}
        {% if movie.vote_average %}<span><i class="fas fa-star" style="color:#f5c518;"></i> {{ "%.1f"|format(movie.vote_average) }}</span>{% endif %}
        {% if movie.languages %}<span><i class="fas fa-language"></i> {{ movie.languages | join(' • ') }}</span>{% endif %}
        {% if movie.genres %}<span>{{ movie.genres | join(' • ') }}</span>{% endif %}
      </div>
      <p class="detail-overview">{{ movie.overview }}</p>
      {% if movie.watch_link %}<a href="{{ movie.watch_link }}" target="_blank" class="action-btn"><i class="fas fa-play"></i> Watch Now</a><a href="{{ movie.watch_link }}" download class="action-btn" style="background-color:#007bff;"><i class="fas fa-download"></i> Download</a>{% endif %}
      {% if ad_settings.banner_ad_code %}<div class="ad-container">{{ ad_settings.banner_ad_code|safe }}</div>{% endif %}
      <div style="margin-top: 20px;"><a href="{{ url_for('contact', report_id=movie._id, title=movie.title) }}" style="color:var(--text-dark);"><i class="fas fa-flag"></i> Report a Problem</a></div>
    </div>
  </div>
</div>
{% if related_movies %}<div class="related-section-container"><h3 class="section-title">You Might Also Like</h3><div class="related-grid">{% for m in related_movies %}{{ render_movie_card(m) }}{% endfor %}</div></div>{% endif %}
{% else %}
<div style="text-align:center; padding-top:20vh;"><h2>404 - Content Not Found</h2><p>The content you are looking for does not exist.</p><a href="{{url_for('home')}}">Go Home</a></div>
{% endif %}
</body></html>
"""
genres_html = """
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" /><title>{{ title }} - MovieZone</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
  :root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; }
  * { box-sizing: border-box; margin: 0; padding: 0; } body { font-family: 'Roboto', sans-serif; background-color: var(--netflix-black); color: var(--text-light); } a { text-decoration: none; color: inherit; }
  .main-container { padding: 100px 50px 50px; } .page-title { font-family: 'Bebas Neue', sans-serif; font-size: 3rem; color: var(--netflix-red); margin-bottom: 30px; }
  .back-button { color: var(--text-light); font-size: 1rem; margin-bottom: 20px; display: inline-block; } .back-button:hover { color: var(--netflix-red); }
  .genre-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
  .genre-card { background: linear-gradient(45deg, #2c2c2c, #1a1a1a); border-radius: 8px; padding: 30px 20px; text-align: center; font-size: 1.4rem; font-weight: 700; transition: all 0.3s ease; border: 1px solid #444; }
  .genre-card:hover { transform: translateY(-5px) scale(1.03); background: linear-gradient(45deg, var(--netflix-red), #b00710); border-color: var(--netflix-red); }
  @media (max-width: 768px) { .main-container { padding: 80px 15px 30px; } .page-title { font-size: 2.2rem; } .genre-grid { grid-template-columns: repeat(2, 1fr); gap: 15px; } .genre-card { font-size: 1.1rem; padding: 25px 15px; } }
</style><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css"></head>
<body>
<div class="main-container"><a href="{{ url_for('home') }}" class="back-button"><i class="fas fa-arrow-left"></i> Back to Home</a><h1 class="page-title">{{ title }}</h1>
<div class="genre-grid">{% for genre in genres %}<a href="{{ url_for('movies_by_genre', genre_name=genre) }}" class="genre-card"><span>{{ genre }}</span></a>{% endfor %}</div></div>
</body></html>
"""
admin_html = """
<!DOCTYPE html>
<html><head><title>Admin Panel - MovieZone</title><meta name="viewport" content="width=device-width, initial-scale=1" /><style>
:root { --netflix-red: #E50914; --netflix-black: #141414; --dark-gray: #222; --light-gray: #333; --text-light: #f5f5f5; }
body { font-family: 'Roboto', sans-serif; background: var(--netflix-black); color: var(--text-light); padding: 20px; }
h2, h3 { font-family: 'Bebas Neue', sans-serif; color: var(--netflix-red); } h2 { font-size: 2.5rem; margin-bottom: 20px; } h3 { font-size: 1.5rem; margin: 20px 0 10px 0;}
form { max-width: 800px; margin: 0 auto 40px auto; background: var(--dark-gray); padding: 25px; border-radius: 8px;}
.form-group { margin-bottom: 15px; } .form-group label { display: block; margin-bottom: 8px; font-weight: bold; }
input[type="text"], input[type="url"], input[type="search"], textarea, select, input[type="number"], input[type="email"] { width: 100%; padding: 12px; border-radius: 4px; border: 1px solid var(--light-gray); font-size: 1rem; background: var(--light-gray); color: var(--text-light); box-sizing: border-box; }
input[type="checkbox"] { width: auto; margin-right: 10px; transform: scale(1.2); } textarea { resize: vertical; min-height: 100px; }
button[type="submit"], .add-btn, .clear-btn { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1rem; transition: background 0.3s ease; text-decoration: none; }
button[type="submit"]:hover, .add-btn:hover { background: #b00710; }
.clear-btn { background: #555; display: inline-block; } .clear-btn:hover { background: #444; }
table { display: block; overflow-x: auto; white-space: nowrap; width: 100%; border-collapse: collapse; margin-top: 20px; }
th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid var(--light-gray); } th { background: #252525; } td { background: var(--dark-gray); }
.action-buttons { display: flex; gap: 10px; } .action-buttons a, .action-buttons button, .delete-btn { padding: 6px 12px; border-radius: 4px; text-decoration: none; color: white; border: none; cursor: pointer; }
.edit-btn { background: #007bff; } .delete-btn { background: #dc3545; }
hr.section-divider { border: 0; height: 2px; background-color: var(--light-gray); margin: 40px 0; }
</style><link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
<body>
  <h2>বিজ্ঞাপন পরিচালনা (Ad Management)</h2>
  <form action="{{ url_for('save_ads') }}" method="post"><div class="form-group"><label>Pop-Under / OnClick Ad Code</label><textarea name="popunder_code" rows="4">{{ ad_settings.popunder_code or '' }}</textarea></div><div class="form-group"><label>Social Bar / Sticky Ad Code</label><textarea name="social_bar_code" rows="4">{{ ad_settings.social_bar_code or '' }}</textarea></div><div class="form-group"><label>ব্যানার বিজ্ঞাপন কোড (Banner Ad)</label><textarea name="banner_ad_code" rows="4">{{ ad_settings.banner_ad_code or '' }}</textarea></div><div class="form-group"><label>নেটিভ ব্যানার বিজ্ঞাপন (Native Banner)</label><textarea name="native_banner_code" rows="4">{{ ad_settings.native_banner_code or '' }}</textarea></div><button type="submit">Save Ad Codes</button></form>
  <hr class="section-divider">
  <h2>Add New Content (Manual)</h2>
  <form method="post" action="{{ url_for('admin') }}" enctype="multipart/form-data">
    <div class="form-group"><label>Title (Required):</label><input type="text" name="title" required /></div>
    <div class="form-group"><label>Watch Link (Embed or Direct URL):</label><input type="url" name="watch_link" /></div>
    <p style="text-align:center; font-weight:bold;">OR</p>
    <div class="form-group"><label>Upload Video File (will be primary if provided):</label><input type="file" name="video_file" accept="video/*" style="padding:10px; background: #444;"></div>
    <hr style="margin: 20px 0;"><button type="submit">Add Content</button>
  </form>
  <hr class="section-divider">
  <h2>Manage Content</h2>
  <form method="GET" action="{{ url_for('admin') }}" style="padding: 15px; background: #252525; display: flex; gap: 10px; align-items: center;">
    <input type="search" name="search" placeholder="Search by title..." value="{{ search_query or '' }}" style="flex-grow: 1;">
    <button type="submit">Search</button>
    {% if search_query %}<a href="{{ url_for('admin') }}" class="clear-btn">Clear</a>{% endif %}
  </form>
  <table><thead><tr><th>Title</th><th>Type</th><th>Actions</th></tr></thead><tbody>
    {% for movie in content_list %}
    <tr><td>{{ movie.title }}</td><td>{{ movie.type | title }}</td><td class="action-buttons"><a href="{{ url_for('edit_movie', movie_id=movie._id) }}" class="edit-btn">Edit</a><button class="delete-btn" onclick="confirmDelete('{{ movie._id }}', '{{ movie.title }}')">Delete</button></td></tr>
    {% else %}
    <tr><td colspan="3" style="text-align: center;">No content found.</td></tr>
    {% endfor %}
  </tbody></table>
  <hr class="section-divider">
  <h2>User Feedback / Reports</h2>
  {% if feedback_list %}<table><thead><tr><th>Date</th><th>Type</th><th>Title</th><th>Message</th><th>Email</th><th>Action</th></tr></thead><tbody>{% for item in feedback_list %}<tr><td style="min-width: 150px;">{{ item.timestamp.strftime('%Y-%m-%d %H:%M') }}</td><td>{{ item.type }}</td><td>{{ item.content_title }}</td><td style="white-space: pre-wrap; min-width: 300px;">{{ item.message }}</td><td>{{ item.email or 'N/A' }}</td><td><a href="{{ url_for('delete_feedback', feedback_id=item._id) }}" class="delete-btn" onclick="return confirm('Delete this feedback?');">Delete</a></td></tr>{% endfor %}</tbody></table>{% else %}<p>No new feedback or reports.</p>{% endif %}
  <script>
    function confirmDelete(id, title) { if (confirm('Delete "' + title + '"?')) window.location.href = '/delete_movie/' + id; }
  </script>
</body></html>
"""
edit_html = """
<!DOCTYPE html>
<html><head><title>Edit Content - MovieZone</title><meta name="viewport" content="width=device-width, initial-scale=1" /><style>
:root { --netflix-red: #E50914; --netflix-black: #141414; --dark-gray: #222; --light-gray: #333; --text-light: #f5f5f5; }
body { font-family: 'Roboto', sans-serif; background: var(--netflix-black); color: var(--text-light); padding: 20px; }
h2, h3 { font-family: 'Bebas Neue', sans-serif; color: var(--netflix-red); } h2 { font-size: 2.5rem; margin-bottom: 20px; }
form { max-width: 800px; margin: 0 auto 40px auto; background: var(--dark-gray); padding: 25px; border-radius: 8px;}
.form-group { margin-bottom: 15px; } label { display: block; margin-bottom: 8px; font-weight: bold; }
input, textarea, select { width: 100%; padding: 12px; border-radius: 4px; border: 1px solid var(--light-gray); font-size: 1rem; background: var(--light-gray); color: var(--text-light); box-sizing: border-box; }
input[type="checkbox"] { width: auto; margin-right: 10px; transform: scale(1.2); }
button[type="submit"] { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1rem; }
.back-to-admin { display: inline-block; margin-bottom: 20px; color: var(--netflix-red); text-decoration: none; font-weight: bold; }
</style><link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
<body>
  <a href="{{ url_for('admin') }}" class="back-to-admin">← Back to Admin</a>
  <h2>Edit: {{ movie.title }}</h2>
  <form method="post">
    <div class="form-group"><label>Title:</label><input type="text" name="title" value="{{ movie.title }}" required /></div>
    <div class="form-group"><label>Watch Link (Embed or Direct URL):</label><input type="url" name="watch_link" value="{{ movie.watch_link or '' }}" /></div>
    <div class="form-group"><label>Poster URL:</label><input type="url" name="poster" value="{{ movie.poster or '' }}" /></div>
    <div class="form-group"><label>Overview:</label><textarea name="overview" rows="5">{{ movie.overview or '' }}</textarea></div>
    <div class="form-group"><label>Genres (comma separated):</label><input type="text" name="genres" value="{{ movie.genres|join(', ') if movie.genres else '' }}" /></div>
    <div class="form-group"><label>Languages (comma separated):</label><input type="text" name="languages" value="{{ movie.languages|join(', ') if movie.languages else '' }}" /></div>
    <div class="form-group"><label>Poster Badge:</label><input type="text" name="poster_badge" value="{{ movie.poster_badge or '' }}" /></div>
    <hr style="margin: 20px 0;">
    <div class="form-group"><input type="checkbox" name="is_trending" value="true" {% if movie.is_trending %}checked{% endif %}><label style="display: inline-block;">Is Trending?</label></div>
    <div class="form-group"><input type="checkbox" name="is_coming_soon" value="true" {% if movie.is_coming_soon %}checked{% endif %}><label style="display: inline-block;">Is Coming Soon?</label></div>
    <button type="submit">Update Content</button>
  </form>
</body></html>
"""
contact_html = """
<!DOCTYPE html>
<html lang="bn"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Contact Us / Report - MovieZone</title><style>
:root { --netflix-red: #E50914; --netflix-black: #141414; --dark-gray: #222; --light-gray: #333; --text-light: #f5f5f5; }
body { font-family: 'Roboto', sans-serif; background: var(--netflix-black); color: var(--text-light); padding: 20px; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.contact-container { max-width: 600px; width: 100%; background: var(--dark-gray); padding: 30px; border-radius: 8px; }
h2 { font-family: 'Bebas Neue', sans-serif; color: var(--netflix-red); font-size: 2.5rem; text-align: center; margin-bottom: 25px; }
.form-group { margin-bottom: 20px; } label { display: block; margin-bottom: 8px; font-weight: bold; }
input, select, textarea { width: 100%; padding: 12px; border-radius: 4px; border: 1px solid var(--light-gray); font-size: 1rem; background: var(--light-gray); color: var(--text-light); box-sizing: border-box; }
textarea { resize: vertical; min-height: 120px; } button[type="submit"] { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1.1rem; width: 100%; }
.success-message { text-align: center; padding: 20px; background-color: #1f4e2c; color: #d4edda; border-radius: 5px; margin-bottom: 20px; }
.back-link { display: block; text-align: center; margin-top: 20px; color: var(--netflix-red); text-decoration: none; font-weight: bold; }
</style><link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
<body><div class="contact-container"><h2>Contact Us</h2>
{% if message_sent %}<div class="success-message"><p>আপনার বার্তা সফলভাবে পাঠানো হয়েছে। ধন্যবাদ!</p></div><a href="{{ url_for('home') }}" class="back-link">← Back to Home</a>
{% else %}<form method="post"><div class="form-group"><label for="type">বিষয় (Subject):</label><select name="type" id="type"><option value="Movie Request" {% if prefill_type == 'Problem Report' %}disabled{% endif %}>Movie/Series Request</option><option value="Problem Report" {% if prefill_type == 'Problem Report' %}selected{% endif %}>Report a Problem</option><option value="General Feedback">General Feedback</option></select></div><div class="form-group"><label for="content_title">মুভি/সিরিজের নাম (Title):</label><input type="text" name="content_title" id="content_title" value="{{ prefill_title }}" required></div><div class="form-group"><label for="message">আপনার বার্তা (Message):</label><textarea name="message" id="message" required></textarea></div><div class="form-group"><label for="email">আপনার ইমেইল (Optional):</label><input type="email" name="email" id="email"></div><input type="hidden" name="reported_content_id" value="{{ prefill_id }}"><button type="submit">Submit</button></form><a href="{{ url_for('home') }}" class="back-link">← Cancel</a>{% endif %}
</div></body></html>
"""
# ======================================================================
# --- হেলপার এবং ব্যাকগ্রাউন্ড প্রসেসিং ফাংশন ---
# ======================================================================
def parse_filename(filename):
    LANGUAGE_MAP = { 'hindi': 'Hindi', 'hin': 'Hindi', 'english': 'English', 'eng': 'English', 'bengali': 'Bengali', 'bangla': 'Bangla', 'ben': 'Bengali', 'tamil': 'Tamil', 'tam': 'Tamil', 'telugu': 'Telugu', 'tel': 'Telugu', 'kannada': 'Kannada', 'kan': 'Kannada', 'malayalam': 'Malayalam', 'mal': 'Malayalam', 'dual audio': ['Hindi', 'English'], 'multi audio': ['Multi Audio'] }
    cleaned_name = filename.replace('.', ' ').replace('_', ' ').strip()
    found_languages = []
    temp_name_for_lang = cleaned_name.lower()
    for keyword, lang_name in LANGUAGE_MAP.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', temp_name_for_lang):
            if isinstance(lang_name, list): found_languages.extend(lang_name)
            else: found_languages.append(lang_name)
    languages = sorted(list(set(found_languages))) if found_languages else []
    series_match = re.search(r'^(.*?)[\s\._-]*(?:S|Season)[\s\._-]?(\d{1,2})[\s\._-]*(?:E|Episode)[\s\._-]?(\d{1,3})', cleaned_name, re.I)
    if series_match:
        title = series_match.group(1).strip()
        season_num, episode_num = int(series_match.group(2)), int(series_match.group(3))
        title = re.sub(r'\b(season|s)\s*\d+\s*$', '', title, flags=re.I).strip()
        title = re.sub(r'\[.*?\]|\(.*?\)', '', title).strip()
        return {'type': 'series', 'title': title.title(), 'season': season_num, 'episode': episode_num, 'languages': languages}
    year_match = re.search(r'\(?(19[5-9]\d|20\d{2})\)?', cleaned_name)
    year, title = (year_match.group(1), cleaned_name[:year_match.start()].strip()) if year_match else (None, cleaned_name)
    junk_patterns = [r'\b(1080p|720p|480p|4k|uhd|web-?dl|bluray|x26[45]|hevc|aac|5\.1)\b', r'\[.*?\]', r'\(.*?\)']
    for lang_key in LANGUAGE_MAP.keys(): title = re.sub(r'\b' + lang_key + r'\b', '', title, flags=re.I)
    for pattern in junk_patterns: title = re.sub(pattern, '', title, flags=re.I)
    return {'type': 'movie', 'title': re.sub(r'\s+', ' ', title).strip().title(), 'year': year, 'languages': languages}

def get_tmdb_details_from_api(title, content_type, year=None):
    if not TMDB_API_KEY: return {}
    search_type = "tv" if content_type == "series" else "movie"
    try:
        search_url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={TMDB_API_KEY}&query={requests.utils.quote(title)}"
        if year and search_type == "movie": search_url += f"&primary_release_year={year}"
        search_res = requests.get(search_url, timeout=5).json()
        if not search_res.get("results"): return {}
        tmdb_id = search_res["results"][0]["id"]
        detail_url = f"https://api.themoviedb.org/3/{search_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        res = requests.get(detail_url, timeout=5).json()
        return {"tmdb_id": tmdb_id, "title": res.get("title") or res.get("name"), "poster": f"https://image.tmdb.org/t/p/w500{res.get('poster_path')}" if res.get('poster_path') else None, "overview": res.get("overview"), "release_date": res.get("release_date") or res.get("first_air_date"), "genres": [g['name'] for g in res.get("genres", [])], "vote_average": res.get("vote_average")}
    except Exception as e: print(f"TMDb API error for '{title}': {e}"); return {}

def get_telegram_file_details(file_id):
    url = f"{TELEGRAM_API_URL}/getFile"
    response = requests.get(url, params={'file_id': file_id})
    res_json = response.json()
    if res_json.get('ok'): return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{res_json['result']['file_path']}"
    return None

def process_and_upload_file(file_id, original_filename):
    print("\n--- [BACKGROUND THREAD] STARTING PROCESS ---")
    print(f"File ID: {file_id}, Original Filename: {original_filename}")
    print(f"S3 client object exists: {bool(s3_client)}")

    if not s3_client:
        print("--- [BACKGROUND THREAD] FATAL: S3 client was not initialized. Aborting process. ---")
        return

    safe_filename = secure_filename(original_filename)
    print(f"Sanitized filename: {safe_filename}")

    download_url = get_telegram_file_details(file_id)
    if not download_url:
        print(f"--- [BACKGROUND THREAD] FAILURE: Could not get Telegram download URL. ---")
        return
    print(f"Got Telegram download URL: {download_url[:50]}...")

    try:
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            print("SUCCESS: Telegram file stream is ready for upload.")
            
            try:
                print(f"Uploading '{safe_filename}' to bucket '{B2_BUCKET_NAME}'...")
                s3_client.upload_fileobj(r.raw, B2_BUCKET_NAME, safe_filename, ExtraArgs={'ContentType': 'video/mp4'})
                uploaded_url = f"https://{B2_BUCKET_NAME}.{B2_ENDPOINT_URL.split('//')[1]}/{safe_filename}"
                print(f"--- [BACKGROUND THREAD] SUCCESS: Uploaded to B2. URL: {uploaded_url} ---")
            except Exception as s3_error:
                print(f"--- [BACKGROUND THREAD] !!!!!!!!!!!!! B2/S3 UPLOAD FAILED !!!!!!!!!!!!! ---")
                print(f"Error Type: {type(s3_error).__name__}")
                print(f"Error Details: {s3_error}")
                return

            parsed_info = parse_filename(original_filename)
            if not parsed_info or not parsed_info['title']:
                print(f"--- [BACKGROUND THREAD] WARNING: Could not parse info from filename. ---")
                return
            print(f"Parsed Info: {parsed_info}")

            tmdb_data = get_tmdb_details_from_api(parsed_info['title'], parsed_info.get('type'), parsed_info.get('year')) or {}
            print(f"TMDb Data Fetched: {bool(tmdb_data)}")
            
            final_title = tmdb_data.get('title') or parsed_info['title']
            query = {"title": final_title}
            
            update_data = {"$set": {"watch_link": uploaded_url, "type": parsed_info.get('type', 'movie'), **{k: v for k, v in tmdb_data.items() if v is not None}}, "$addToSet": {"languages": {"$each": parsed_info.get('languages', [])}}}
            
            result = movies.update_one(query, update_data, upsert=True)
            print(f"--- [BACKGROUND THREAD] SUCCESS: Database updated for '{final_title}'. Matched: {result.matched_count}, Modified: {result.modified_count}, UpsertedId: {result.upserted_id} ---")

    except requests.exceptions.RequestException as req_error:
        print(f"--- [BACKGROUND THREAD] !!!!!!!!!!!!! TELEGRAM DOWNLOAD FAILED !!!!!!!!!!!!! ---")
        print(f"Error Details: {req_error}")
    except Exception as e:
        print(f"--- [BACKGROUND THREAD] !!!!!!!!!!!!! AN UNEXPECTED ERROR OCCURRED !!!!!!!!!!!!! ---")
        print(f"Error Details: {e}")

def process_movie_list(movie_list):
    for item in movie_list:
        if '_id' in item: item['_id'] = str(item['_id'])
    return movie_list

# ======================================================================
# --- Flask Routes ---
# ======================================================================
@app.route('/')
def home():
    query = request.args.get('q')
    if query:
        movies_list = list(movies.find({"title": {"$regex": query, "$options": "i"}}).sort('_id', -1))
        return render_template_string(index_html, movies=process_movie_list(movies_list), query=f'Results for "{query}"', is_full_page_list=True)
    limit = 12
    context = {
        "trending_movies": process_movie_list(list(movies.find({"is_trending": True, "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "latest_movies": process_movie_list(list(movies.find({"type": "movie", "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "latest_series": process_movie_list(list(movies.find({"type": "series", "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "coming_soon_movies": process_movie_list(list(movies.find({"is_coming_soon": True}).sort('_id', -1).limit(limit))),
        "recently_added": process_movie_list(list(movies.find({"is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(6))),
        "recently_added_full": process_movie_list(list(movies.find({"is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "is_full_page_list": False, "query": ""
    }
    return render_template_string(index_html, **context)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    try:
        movie = movies.find_one({"_id": ObjectId(movie_id)})
        if not movie: return render_template_string(detail_html, movie=None), 404
        related_movies = []
        if movie.get("genres"):
            related_movies = list(movies.find({"genres": {"$in": movie["genres"]}, "_id": {"$ne": ObjectId(movie_id)}}).limit(12))
        return render_template_string(detail_html, movie=movie, related_movies=process_movie_list(related_movies))
    except Exception:
        return render_template_string(detail_html, movie=None), 404

def render_full_list(content_list, title):
    return render_template_string(index_html, movies=process_movie_list(content_list), query=title, is_full_page_list=True)

@app.route('/badge/<badge_name>')
def movies_by_badge(badge_name): return render_full_list(list(movies.find({"poster_badge": badge_name}).sort('_id', -1)), f'Tag: {badge_name}')
@app.route('/genres')
def genres_page(): return render_template_string(genres_html, genres=sorted([g for g in movies.distinct("genres") if g]), title="Browse by Genre")
@app.route('/genre/<genre_name>')
def movies_by_genre(genre_name): return render_full_list(list(movies.find({"genres": genre_name}).sort('_id', -1)), f'Genre: {genre_name}')
@app.route('/trending_movies')
def trending_movies(): return render_full_list(list(movies.find({"is_trending": True, "is_coming_soon": {"$ne": True}}).sort('_id', -1)), "Trending Now")
@app.route('/movies_only')
def movies_only(): return render_full_list(list(movies.find({"type": "movie", "is_coming_soon": {"$ne": True}}).sort('_id', -1)), "All Movies")
@app.route('/webseries')
def webseries(): return render_full_list(list(movies.find({"type": "series", "is_coming_soon": {"$ne": True}}).sort('_id', -1)), "All Web Series")
@app.route('/coming_soon')
def coming_soon(): return render_full_list(list(movies.find({"is_coming_soon": True}).sort('_id', -1)), "Coming Soon")
@app.route('/recently_added')
def recently_added_all(): return render_full_list(list(movies.find({"is_coming_soon": {"$ne": True}}).sort('_id', -1)), "Recently Added")

@app.route('/admin', methods=["GET", "POST"])
@requires_auth
def admin():
    if request.method == "POST":
        title = request.form.get("title")
        watch_link = request.form.get("watch_link")
        video_file = request.files.get('video_file')
        if video_file and video_file.filename != '':
            if not s3_client: return "S3 client not configured.", 500
            filename = secure_filename(video_file.filename)
            try:
                s3_client.upload_fileobj(video_file, B2_BUCKET_NAME, filename, ExtraArgs={'ContentType': video_file.content_type})
                watch_link = f"https://{B2_BUCKET_NAME}.{B2_ENDPOINT_URL.split('//')[1]}/{filename}"
            except Exception as e: return f"Error uploading to S3: {e}", 500
        parsed_info = parse_filename(title)
        tmdb_data = get_tmdb_details_from_api(parsed_info['title'], 'movie', parsed_info.get('year')) or {}
        movie_data = {**parsed_info, **tmdb_data, "title": tmdb_data.get('title', title), "watch_link": watch_link}
        movies.insert_one(movie_data)
        return redirect(url_for('admin'))
    search_query = request.args.get('search', '').strip()
    query_filter = {}
    if search_query: query_filter = {"title": {"$regex": search_query, "$options": "i"}}
    content_list = process_movie_list(list(movies.find(query_filter).sort('_id', -1)))
    feedback_list = process_movie_list(list(feedback.find().sort('timestamp', -1)))
    return render_template_string(admin_html, content_list=content_list, feedback_list=feedback_list, search_query=search_query)

@app.route('/edit_movie/<movie_id>', methods=["GET", "POST"])
@requires_auth
def edit_movie(movie_id):
    movie_obj = movies.find_one({"_id": ObjectId(movie_id)})
    if not movie_obj: return "Movie not found", 404
    if request.method == "POST":
        update_data = {"title": request.form.get("title"), "watch_link": request.form.get("watch_link"), "poster": request.form.get("poster"), "overview": request.form.get("overview"), "genres": [g.strip() for g in request.form.get("genres", "").split(',') if g.strip()], "languages": [lang.strip() for lang in request.form.get("languages", "").split(',') if lang.strip()], "poster_badge": request.form.get("poster_badge", "").strip() or None, "is_trending": request.form.get("is_trending") == "true", "is_coming_soon": request.form.get("is_coming_soon") == "true" }
        movies.update_one({"_id": ObjectId(movie_id)}, {"$set": update_data})
        return redirect(url_for('admin'))
    return render_template_string(edit_html, movie=movie_obj)

@app.route('/delete_movie/<movie_id>')
@requires_auth
def delete_movie(movie_id):
    movies.delete_one({"_id": ObjectId(movie_id)})
    return redirect(url_for('admin'))

@app.route('/admin/save_ads', methods=['POST'])
@requires_auth
def save_ads():
    ad_codes = {"popunder_code": request.form.get("popunder_code"), "social_bar_code": request.form.get("social_bar_code"), "banner_ad_code": request.form.get("banner_ad_code"), "native_banner_code": request.form.get("native_banner_code")}
    settings.update_one({}, {"$set": ad_codes}, upsert=True)
    return redirect(url_for('admin'))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        feedback_data = {"type": request.form.get("type"), "content_title": request.form.get("content_title"), "message": request.form.get("message"), "email": request.form.get("email"), "reported_content_id": request.form.get("reported_content_id"), "timestamp": datetime.utcnow()}
        feedback.insert_one(feedback_data)
        return render_template_string(contact_html, message_sent=True)
    prefill_title, prefill_id = request.args.get('title', ''), request.args.get('report_id', '')
    prefill_type = 'Problem Report' if prefill_id else 'Movie Request'
    return render_template_string(contact_html, message_sent=False, prefill_title=prefill_title, prefill_id=prefill_id, prefill_type=prefill_type)

@app.route('/delete_feedback/<feedback_id>')
@requires_auth
def delete_feedback(feedback_id):
    feedback.delete_one({"_id": ObjectId(feedback_id)})
    return redirect(url_for('admin'))

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        if str(post.get('chat', {}).get('id')) != ADMIN_CHANNEL_ID: return jsonify(status='ok', reason='not_admin_channel')
        file = post.get('video') or post.get('document')
        if file and file.get('file_name'):
            thread = Thread(target=process_and_upload_file, args=(file['file_id'], file['file_name']))
            thread.start()
            print(f"Webhook received for {file['file_name']}. Handed over to background thread.")
            return jsonify(status='ok', reason='processing_started')
    return jsonify(status='ok', reason='no_action_taken')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
