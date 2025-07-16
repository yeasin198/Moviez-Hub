import os
import sys
import re
import requests
import time
from flask import Flask, render_template_string, request, redirect, url_for, Response, jsonify
from pymongo import MongoClient, TEXT
from bson.objectid import ObjectId
from functools import wraps
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

# ======================================================================
# --- আপনার ব্যক্তিগত ও অ্যাডমিন তথ্য (এনভায়রনমেন্ট থেকে লোড হবে) ---
# ======================================================================
MONGO_URI = os.environ.get("MONGO_URI")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
ADMIN_CHANNEL_ID = os.environ.get("ADMIN_CHANNEL_ID")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
LINK_GENERATOR_BOT_USERNAME = os.environ.get("LINK_GENERATOR_BOT_USERNAME")
LINK_CAPTURE_CHANNEL_ID = os.environ.get("LINK_CAPTURE_CHANNEL_ID")

required_vars = {
    "MONGO_URI": MONGO_URI, "BOT_TOKEN": BOT_TOKEN, "TMDB_API_KEY": TMDB_API_KEY,
    "ADMIN_CHANNEL_ID": ADMIN_CHANNEL_ID, "BOT_USERNAME": BOT_USERNAME,
    "ADMIN_USERNAME": ADMIN_USERNAME, "ADMIN_PASSWORD": ADMIN_PASSWORD,
    "LINK_GENERATOR_BOT_USERNAME": LINK_GENERATOR_BOT_USERNAME,
    "LINK_CAPTURE_CHANNEL_ID": LINK_CAPTURE_CHANNEL_ID
}
missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    print(f"FATAL: Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

# ======================================================================
# --- অ্যাপ্লিকেশন সেটআপ ---
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)

# --- অ্যাডমিন, ডাটাবেস, কনটেক্সট এবং সিডিউলার ---
def check_auth(username, password): return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
def authenticate(): return Response('Could not verify your access level.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password): return authenticate()
        return f(*args, **kwargs)
    return decorated

try:
    client = MongoClient(MONGO_URI)
    db = client["movie_db"]
    movies, settings, feedback = db["movies"], db["settings"], db["feedback"]
    movies.create_index([("type", 1), ("is_coming_soon", 1), ("_id", -1)])
    movies.create_index([("is_trending", 1), ("is_coming_soon", 1), ("_id", -1)])
    movies.create_index("genres")
    movies.create_index("tmdb_id", unique=True, sparse=True)
    movies.create_index([("title", TEXT)], default_language='none')
    print("SUCCESS: Successfully connected to MongoDB and ensured indexes!")
except Exception as e:
    print(f"FATAL: Error connecting to MongoDB or creating indexes: {e}"); sys.exit(1)

@app.context_processor
def inject_vars(): return dict(ad_settings=(settings.find_one() or {}), bot_username=BOT_USERNAME)
scheduler = BackgroundScheduler(daemon=True)
def delete_message_after_delay(chat_id, message_id):
    try: requests.post(f"{TELEGRAM_API_URL}/deleteMessage", json={'chat_id': chat_id, 'message_id': message_id})
    except Exception as e: print(f"Error in delete_message_after_delay: {e}")
scheduler.start()

# ======================================================================
# --- HTML টেমপ্লেট ---
# ======================================================================
index_html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
<title>MovieZone - Your Entertainment Hub</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
  :root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; --text-dark: #a0a0a0; --nav-height: 60px; --watch-btn-color: #1ce783; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Roboto', sans-serif; background-color: var(--netflix-black); color: var(--text-light); overflow-x: hidden; }
  a { text-decoration: none; color: inherit; }
  ::-webkit-scrollbar { width: 8px; height: 8px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #444; border-radius: 10px; } ::-webkit-scrollbar-thumb:hover { background: var(--netflix-red); }
  
  .main-nav { position: fixed; top: 0; left: 0; width: 100%; padding: 10px 15px; display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 20px; z-index: 100; transition: background-color 0.3s ease; background: linear-gradient(to bottom, rgba(0,0,0,0.8) 10%, rgba(0,0,0,0)); }
  .main-nav.scrolled { background-color: var(--netflix-black); }
  .nav-left { display: flex; align-items: center; gap: 15px; }
  .hamburger-btn { background: none; border: none; color: white; font-size: 24px; cursor: pointer; padding: 5px; }
  .logo { font-family: 'Bebas Neue', sans-serif; font-size: 28px; color: var(--netflix-red); font-weight: 700; letter-spacing: 1px; }
  .search-form { display: flex; position: relative; }
  .search-input { background-color: rgba(255,255,255,0.1); border: 1px solid #444; color: var(--text-light); padding: 10px 40px 10px 15px; border-radius: 50px; transition: background-color 0.3s ease; width: 100%; }
  .search-input:focus { background-color: rgba(255,255,255,0.2); border-color: var(--text-light); outline: none; }
  .search-icon-btn { position: absolute; right: 0; top: 0; height: 100%; background: transparent; border: none; color: #aaa; padding: 0 15px; cursor: pointer; }

  .side-menu { position: fixed; top: 0; left: 0; width: 280px; height: 100%; background-color: #181818; z-index: 1001; transform: translateX(-100%); transition: transform 0.3s ease-in-out; }
  .side-menu.active { transform: translateX(0); }
  .side-menu-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 15px; border-bottom: 1px solid #333; }
  .close-btn { background: none; border: none; color: white; font-size: 30px; cursor: pointer; }
  .side-menu-nav { display: flex; flex-direction: column; padding-top: 20px; }
  .side-menu-link { color: var(--text-dark); text-decoration: none; padding: 15px 20px; font-size: 1.1rem; display: flex; align-items: center; gap: 15px; transition: background-color 0.2s, color 0.2s; }
  .side-menu-link:hover, .side-menu-link.active { background-color: var(--netflix-red); color: white; }
  .overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.7); z-index: 1000; opacity: 0; visibility: hidden; transition: opacity 0.3s, visibility 0.3s; }
  .overlay.active { opacity: 1; visibility: visible; }

  .hero-section-wrapper { display: flex; flex-direction: column; align-items: center; margin-top: calc(var(--nav-height) + 20px); padding: 0 15px; }
  .hero-slider-container { position: relative; width: 100%; max-width: 800px; overflow: hidden; border-radius: 16px; }
  .hero-slider-wrapper { display: flex; transition: transform 0.5s ease-in-out; }
  .hero-slide { min-width: 100%; position: relative; aspect-ratio: 16/9; background-color: #222; }
  .hero-slide-img { position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; }
  .hero-slide::after { content: ''; position: absolute; inset: 0; background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 50%); }
  .hero-content { position: absolute; bottom: 8%; left: 5%; right: 5%; z-index: 2; color: white; }
  .hero-title { font-family: 'Roboto', sans-serif; font-weight: 700; font-size: 1.2rem; line-height: 1.2; margin-bottom: 0.4em; text-shadow: 2px 2px 8px rgba(0,0,0,0.8); }
  .hero-overview { font-size: 0.85rem; line-height: 1.4; color: #ccc; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 1em; text-shadow: 1px 1px 4px rgba(0,0,0,0.8); }
  .hero-buttons { display: flex; gap: 10px; align-items: center; }
  .hero-buttons .btn { padding: 10px 20px; border: none; border-radius: 50px; font-size: 0.9rem; font-weight: 700; cursor: pointer; transition: transform 0.2s ease; display: inline-flex; align-items: center; gap: 8px; }
  .hero-buttons .btn:hover { transform: scale(1.05); }
  .btn-watch { background-color: var(--watch-btn-color); color: #000; }
  .btn-rating { background-color: rgba(40, 40, 40, 0.7); color: white; backdrop-filter: blur(5px); }
  .btn-rating .fa-star { color: #f5c518; }
  .hero-controls { display: flex; gap: 15px; margin-top: 20px; }
  .hero-arrow { background: transparent; border: 2px solid #555; color: #999; width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1rem; cursor: pointer; transition: all 0.2s; }
  .hero-arrow:hover { background-color: #555; color: white; }

  main { padding: 0 15px; margin-top: 40px;}
  .category-section { margin: 40px 0; }
  .category-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
  .category-title { font-family: 'Roboto', sans-serif; font-weight: 700; font-size: 1.4rem; margin: 0; }
  .see-all-link { color: var(--text-dark); font-weight: 700; font-size: 0.9rem; }
  .category-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 20px 10px; }
  .movie-card { display: block; cursor: pointer; transition: transform 0.3s ease; }
  .poster-wrapper { position: relative; width: 100%; border-radius: 6px; overflow: hidden; background-color: #222; display: flex; flex-direction: column; }
  .movie-poster-container { position: relative; overflow: hidden; width:100%; flex-grow:1; aspect-ratio: 2 / 3; }
  .movie-poster { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.4s ease; }
  
  .full-page-grid-container { padding-top: 100px; padding-bottom: 50px; }
  .full-page-grid-title { font-size: 2rem; }
  .full-page-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 20px 10px; }
  
  @media (min-width: 769px) {
    main { padding: 0 50px; }
    .search-form { width: 300px; }
    .hero-section-wrapper { padding: 0 50px; }
    .hero-title { font-size: 2rem; }
    .hero-overview { font-size: 1rem; }
    .hero-buttons .btn { font-size: 1rem; }
    .category-grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 25px 15px; }
  }
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
<header class="main-nav">
  <div class="nav-left">
    <button class="hamburger-btn" id="hamburger-menu"><i class="fas fa-bars"></i></button>
    <a href="{{ url_for('home') }}" class="logo">MovieZone</a>
  </div>
  <form method="GET" action="/" class="search-form">
      <input type="search" name="q" class="search-input" placeholder="Search..." value="{{ query|default('') }}" />
      <button type="submit" class="search-icon-btn"><i class="fas fa-search"></i></button>
  </form>
</header>
<div class="side-menu" id="side-menu-container">
    <div class="side-menu-header"> <a href="{{ url_for('home') }}" class="logo">MovieZone</a> <button class="close-btn" id="close-menu-btn">×</button> </div>
    <nav class="side-menu-nav">
        <a href="{{ url_for('home') }}" class="side-menu-link active"><i class="fas fa-home"></i> Home</a>
        <a href="{{ url_for('movies_only') }}" class="side-menu-link"><i class="fas fa-film"></i> Movies</a>
        <a href="{{ url_for('webseries') }}" class="side-menu-link"><i class="fas fa-tv"></i> Series</a>
        <a href="{{ url_for('genres_page') }}" class="side-menu-link"><i class="fas fa-layer-group"></i> Genres</a>
        <a href="{{ url_for('contact') }}" class="side-menu-link"><i class="fas fa-envelope"></i> Request</a>
    </nav>
</div>
<div class="overlay" id="overlay"></div>
<main>
  {% macro render_movie_card(m) %}
    <a href="{{ url_for('movie_detail', movie_id=m._id) }}" class="movie-card">
      <div class="poster-wrapper">
        <div class="movie-poster-container"><img class="movie-poster" loading="lazy" src="{{ m.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ m.title }}"></div>
        <div class="card-info-static"> <h4 class="card-info-title">{{ m.title }}</h4> {% if m.release_date %}<p class="card-info-meta">{{ m.release_date.split('-')[0] }}</p>{% endif %} </div>
      </div>
    </a>
  {% endmacro %}
  {% if is_full_page_list %}
    <div class="full-page-grid-container"><h2 class="full-page-grid-title">{{ query }}</h2>
        {% if movies|length == 0 %}<p style="text-align:center; color: var(--text-dark); margin-top: 40px;">No content found.</p>
        {% else %}<div class="category-grid">{% for m in movies %}{{ render_movie_card(m) }}{% endfor %}</div>{% endif %}
    </div>
  {% else %}
    {% if recently_added %}
    <div class="hero-section-wrapper">
        <div class="hero-slider-container">
            <div class="hero-slider-wrapper" id="hero-slider">
                {% for movie in recently_added %}
                <div class="hero-slide">
                    <img src="{{ movie.backdrop or movie.poster or 'https://via.placeholder.com/1280x720.png?text=No+Image' }}" alt="{{ movie.title }} backdrop" class="hero-slide-img">
                    <div class="hero-content">
                        <h2 class="hero-title">{{ movie.title }}</h2>
                        <p class="hero-overview">{{ movie.overview }}</p>
                        <div class="hero-buttons">
                            {% if movie.watch_link and not movie.is_coming_soon %}<a href="{{ url_for('watch_movie', movie_id=movie._id) }}" class="btn btn-watch"><i class="fas fa-play"></i> Watch</a>{% endif %}
                            {% if movie.vote_average %}<a href="{{ url_for('movie_detail', movie_id=movie._id) }}" class="btn btn-rating"><i class="fas fa-star"></i> {{ "%.1f"|format(movie.vote_average) }}</a>{% endif %}
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="hero-controls">
            <button class="hero-arrow prev" id="hero-prev"><i class="fas fa-chevron-left"></i></button>
            <button class="hero-arrow next" id="hero-next"><i class="fas fa-chevron-right"></i></button>
        </div>
    </div>
    {% endif %}
    {% macro render_grid_section(title, movies_list, endpoint) %}
        {% if movies_list %}<div class="category-section">
            <div class="category-header"> <h2 class="category-title">{{ title }}</h2> <a href="{{ url_for(endpoint) }}" class="see-all-link">See All ></a> </div>
            <div class="category-grid"> {% for m in movies_list %}{{ render_movie_card(m) }}{% endfor %} </div>
        </div>{% endif %}
    {% endmacro %}
    {{ render_grid_section('Trending Now', trending_movies, 'trending_movies') }}
    {% if ad_settings.banner_ad_code %}<div class="ad-container">{{ ad_settings.banner_ad_code|safe }}</div>{% endif %}
    {{ render_grid_section('Latest Movies', latest_movies, 'movies_only') }}
    {% if ad_settings.native_banner_code %}<div class="ad-container">{{ ad_settings.native_banner_code|safe }}</div>{% endif %}
    {{ render_grid_section('Web Series', latest_series, 'webseries') }}
    {{ render_grid_section('Coming Soon', coming_soon_movies, 'coming_soon') }}
  {% endif %}
</main>
<script>
    const nav = document.querySelector('.main-nav');
    window.addEventListener('scroll', () => { window.scrollY > 50 ? nav.classList.add('scrolled') : nav.classList.remove('scrolled'); });
    const hamburgerBtn = document.getElementById('hamburger-menu'), closeMenuBtn = document.getElementById('close-menu-btn'), sideMenu = document.getElementById('side-menu-container'), overlay = document.getElementById('overlay');
    function toggleMenu() { sideMenu.classList.toggle('active'); overlay.classList.toggle('active'); }
    hamburgerBtn.addEventListener('click', toggleMenu); closeMenuBtn.addEventListener('click', toggleMenu); overlay.addEventListener('click', toggleMenu);
    document.addEventListener('DOMContentLoaded', function() {
        const slider = document.getElementById('hero-slider');
        const prevBtn = document.getElementById('hero-prev');
        const nextBtn = document.getElementById('hero-next');
        if (slider) {
            const slides = slider.querySelectorAll('.hero-slide');
            if (slides.length > 1) {
                let currentIndex = 0, slideInterval;
                function goToSlide(index) { slider.style.transform = 'translateX(' + (-100 * index) + '%)'; currentIndex = index; }
                function nextSlide() { goToSlide((currentIndex + 1) % slides.length); }
                function prevSlide() { goToSlide((currentIndex - 1 + slides.length) % slides.length); }
                function startSlider() { slideInterval = setInterval(nextSlide, 5000); }
                nextBtn.addEventListener('click', () => { clearInterval(slideInterval); nextSlide(); startSlider(); });
                prevBtn.addEventListener('click', () => { clearInterval(slideInterval); prevSlide(); startSlider(); });
                startSlider();
            } else if (prevBtn && nextBtn) { prevBtn.style.display = 'none'; nextBtn.style.display = 'none'; }
        }
    });
</script>
</body>
</html>
"""

detail_html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" /><title>{{ movie.title if movie else "Content Not Found" }} - MovieZone</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;500;700&display=swap');
  :root { --netflix-red: #E50914; --netflix-black: #141414; --text-light: #f5f5f5; --text-dark: #a0a0a0; }
  * { box-sizing: border-box; margin: 0; padding: 0; } body { font-family: 'Roboto', sans-serif; background: var(--netflix-black); color: var(--text-light); }
  .detail-header { position: absolute; top: 0; left: 0; right: 0; padding: 20px 50px; z-index: 100; }
  .back-button { color: var(--text-light); font-size: 1.2rem; font-weight: 700; text-decoration: none; display: flex; align-items: center; gap: 10px; transition: color 0.3s ease; }
  .back-button:hover { color: var(--netflix-red); }
  .detail-hero { position: relative; width: 100%; display: flex; align-items: center; justify-content: center; padding: 100px 0; }
  .detail-hero-background { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background-size: cover; background-position: center; filter: blur(20px) brightness(0.4); transform: scale(1.1); }
  .detail-hero::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to top, rgba(20,20,20,1) 0%, rgba(20,20,20,0.6) 50%, rgba(20,20,20,1) 100%); }
  .detail-content-wrapper { position: relative; z-index: 2; display: flex; gap: 40px; max-width: 1200px; padding: 0 50px; width: 100%; }
  .detail-poster { width: 300px; height: 450px; flex-shrink: 0; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); object-fit: cover; }
  .detail-info { flex-grow: 1; max-width: 65%; }
  .detail-title { font-family: 'Bebas Neue', sans-serif; font-size: 4.5rem; font-weight: 700; line-height: 1.1; margin-bottom: 20px; }
  .detail-meta { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 25px; font-size: 1rem; color: var(--text-dark); }
  .detail-meta span { font-weight: 700; color: var(--text-light); }
  .detail-meta span i { margin-right: 5px; color: var(--text-dark); }
  .detail-overview { font-size: 1.1rem; line-height: 1.6; margin-bottom: 30px; }
  .action-btn { background-color: var(--netflix-red); color: white; padding: 15px 30px; font-size: 1.2rem; font-weight: 700; border: none; border-radius: 5px; cursor: pointer; display: block; text-align: center; gap: 10px; text-decoration: none; margin-bottom: 15px; transition: all 0.2s ease; }
  .action-btn:hover { transform: scale(1.05); background-color: #f61f29; }
  .section-title { font-size: 1.5rem; font-weight: 700; margin-bottom: 20px; padding-bottom: 5px; border-bottom: 2px solid var(--netflix-red); display: inline-block; }
  .video-container { position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; background: #000; border-radius: 8px; margin-top: 20px; }
  .video-container iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
  .links-section { margin-top: 30px; }
  .link-button { display: block; padding: 12px 25px; background-color: #444; color: white; text-decoration: none; border-radius: 4px; font-weight: 700; transition: background-color 0.3s ease; margin-bottom: 10px; text-align: center; }
  .link-button.telegram { background-color: #2AABEE; }
  .episode-section { margin-top: 30px; }
  .episode-item { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 15px; border-radius: 5px; background-color: #1a1a1a; border-left: 4px solid var(--netflix-red); }
  .episode-title { font-size: 1.1rem; font-weight: 500; color: #fff; }
  .ad-container { margin: 30px 0; text-align: center; }
  .related-section-container { padding: 40px 0; background-color: #181818; }
  .related-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px 15px; padding: 0 50px; }
  .related-grid .movie-card { width: auto; }
  .related-grid .poster-wrapper { position: relative; width: 100%; border-radius: 6px; overflow: hidden; background-color: #222; display: flex; flex-direction: column; }
  .related-grid .movie-poster-container { position: relative; overflow: hidden; width:100%; flex-grow:1; aspect-ratio: 2 / 3; }
  .related-grid .movie-poster { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.4s ease; }
  @media (max-width: 992px) { .detail-content-wrapper { flex-direction: column; align-items: center; text-align: center; } .detail-info { max-width: 100%; } .detail-title { font-size: 3.5rem; } }
  @media (max-width: 768px) { .detail-header { padding: 20px; } .detail-hero { padding: 80px 20px 40px; } .detail-poster { width: 60%; max-width: 220px; height: auto; } .detail-title { font-size: 2.2rem; }
  .action-btn, .link-button { display: block; width: 100%; max-width: 320px; margin: 0 auto 10px auto; }
  .episode-item { flex-direction: column; align-items: flex-start; gap: 10px; }
  .section-title { margin-left: 15px !important; } .related-section-container { padding: 20px 0; }
  .related-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 15px 10px; padding: 0 15px; } }
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
</head>
<body>
{% macro render_related_movie_card(m) %}
  <a href="{{ url_for('movie_detail', movie_id=m._id) }}" class="movie-card">
    <div class="poster-wrapper">
      <div class="movie-poster-container"><img class="movie-poster" loading="lazy" src="{{ m.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ m.title }}"></div>
      <div class="card-info-static"><h4 class="card-info-title">{{ m.title }}</h4>{% if m.release_date %}<p class="card-info-meta">{{ m.release_date.split('-')[0] }}</p>{% endif %}</div>
    </div>
  </a>
{% endmacro %}
<header class="detail-header"><a href="javascript:history.back()" class="back-button"><i class="fas fa-arrow-left"></i> Back</a></header>
{% if movie %}
<div class="detail-hero" style="min-height: auto; padding-bottom: 60px;">
  <div class="detail-hero-background" style="background-image: url('{{ movie.backdrop or movie.poster }}');"></div>
  <div class="detail-content-wrapper"><img class="detail-poster" src="{{ movie.poster or 'https://via.placeholder.com/400x600.png?text=No+Image' }}" alt="{{ movie.title }}">
    <div class="detail-info">
      <h1 class="detail-title">{{ movie.title }}</h1>
      <div class="detail-meta">
        {% if movie.release_date %}<span>{{ movie.release_date.split('-')[0] }}</span>{% endif %}
        {% if movie.vote_average %}<span><i class="fas fa-star" style="color:#f5c518;"></i> {{ "%.1f"|format(movie.vote_average) }}</span>{% endif %}
        {% if movie.languages %}<span><i class="fas fa-language"></i> {{ movie.languages | join(' • ') }}</span>{% endif %}
        {% if movie.genres %}<span>{{ movie.genres | join(' • ') }}</span>{% endif %}
      </div>
      <p class="detail-overview">{{ movie.overview }}</p>
      {% if ad_settings.banner_ad_code %}<div class="ad-container">{{ ad_settings.banner_ad_code|safe }}</div>{% endif %}
      {% if movie.is_coming_soon %}<h3 class="section-title">Coming Soon</h3>
      {% elif movie.type == 'movie' %}<div class="links-section">
            {% if movie.watch_link %}<h3 class="section-title">Watch Online</h3><a href="{{ url_for('watch_movie', movie_id=movie._id) }}" class="action-btn"><i class="fas fa-play"></i> Watch Now</a>{% endif %}
            {% if movie.links %}<h3 class="section-title" style="margin-top: 20px;">Download Links</h3>{% for link_item in movie.links | sort(attribute='quality', reverse=True) %}<a class="link-button" href="{{ link_item.url }}" target="_blank" rel="noopener"><i class="fas fa-download"></i> Download {{ link_item.quality }}</a>{% endfor %}{% endif %}
            {% if movie.terabox_links %}<h3 class="section-title" style="margin-top: 20px;">TeraBox Links</h3>{% for link_item in movie.terabox_links | sort(attribute='quality', reverse=True) %}<a class="link-button" href="{{ link_item.url }}" target="_blank" rel="noopener"><i class="fas fa-cloud-download-alt"></i> TeraBox {{ link_item.quality }}</a>{% endfor %}{% endif %}
            {% if movie.files %}<h3 class="section-title" style="margin-top: 20px;">Get from Telegram</h3>{% for file in movie.files | sort(attribute='quality', reverse=True) %}<a href="https://t.me/{{ bot_username }}?start={{ movie._id }}_{{ file.quality }}" class="link-button telegram"><i class="fa-brands fa-telegram"></i> Get {{ file.quality }}</a>{% endfor %}{% endif %}
        </div>
      {% elif movie.type == 'series' %}<div class="episode-section">
          <h3 class="section-title">Episodes</h3>
          {% if movie.episodes %}{% for ep in movie.episodes | sort(attribute='episode_number') | sort(attribute='season') %}<div class="episode-item"><span class="episode-title">Season {{ ep.season }} - Episode {{ ep.episode_number }}</span><a href="https://t.me/{{ bot_username }}?start={{ movie._id }}_{{ ep.season }}_{{ ep.episode_number }}" class="link-button telegram" style="margin-bottom: 0;"><i class="fa-brands fa-telegram"></i> Get Episode</a></div>{% endfor %}{% else %}<p>No episodes available yet.</p>{% endif %}
        </div>
      {% endif %}
      {% if trailer_key %}<div class="trailer-section" style="margin-top: 30px;"><h3 class="section-title">Watch Trailer</h3><div class="video-container"><iframe src="https://www.youtube.com/embed/{{ trailer_key }}" frameborder="0" allowfullscreen></iframe></div></div>{% endif %}
      <div style="margin: 20px 0;"><a href="{{ url_for('contact', report_id=movie._id, title=movie.title) }}" class="link-button" style="background-color:#5a5a5a; text-align:center;"><i class="fas fa-flag"></i> Report a Problem</a></div>
    </div>
  </div>
</div>
{% if related_movies %}<div class="related-section-container"><h3 class="section-title" style="margin-left: 50px; color: white;">You Might Also Like</h3><div class="related-grid">{% for m in related_movies %}{{ render_related_movie_card(m) }}{% endfor %}</div></div>{% endif %}
{% else %}<div style="display:flex; justify-content:center; align-items:center; height:100vh;"><h2>Content not found.</h2></div>{% endif %}
</body>
</html>
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

watch_html = """
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Watching: {{ title }}</title>
<style> body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; background-color: #000; } .player-container { width: 100%; height: 100%; } .player-container iframe { width: 100%; height: 100%; border: 0; } </style></head>
<body><div class="player-container"><iframe src="{{ watch_link }}" allowfullscreen allowtransparency allow="autoplay" scrolling="no" frameborder="0"></iframe></div>
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
button[type="submit"], .add-btn, .clear-btn, .utility-btn { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1rem; transition: background 0.3s ease; text-decoration: none; display: inline-block; }
button[type="submit"]:hover, .add-btn:hover, .utility-btn:hover { background: #b00710; }
.clear-btn { background: #555; } .clear-btn:hover { background: #444; }
.utility-btn { background-color: #007bff; margin-top: 10px; }
table { display: block; overflow-x: auto; white-space: nowrap; width: 100%; border-collapse: collapse; margin-top: 20px; }
th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid var(--light-gray); } th { background: #252525; } td { background: var(--dark-gray); }
.action-buttons { display: flex; gap: 10px; } .action-buttons a, .action-buttons button, .delete-btn { padding: 6px 12px; border-radius: 4px; text-decoration: none; color: white; border: none; cursor: pointer; }
.edit-btn { background: #007bff; } .delete-btn { background: #dc3545; }
.dynamic-item { border: 1px solid var(--light-gray); padding: 15px; margin-bottom: 15px; border-radius: 5px; }
hr.section-divider { border: 0; height: 2px; background-color: var(--light-gray); margin: 40px 0; }
.link-section { border-left: 3px solid var(--netflix-red); padding-left: 15px; margin-top: 20px;}
</style><link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
<body>
  <h2>Admin Panel</h2>
  <a href="{{ url_for('update_all_backdrops') }}" class="utility-btn" onclick="return confirm('This will update all old content with new backdrops from TMDB. This might take a while. Continue?')">Update All Backdrops</a>
  <hr class="section-divider">
  <h2>বিজ্ঞাপন পরিচালনা (Ad Management)</h2>
  <form action="{{ url_for('save_ads') }}" method="post"><div class="form-group"><label>Pop-Under / OnClick Ad Code</label><textarea name="popunder_code" rows="4">{{ ad_settings.popunder_code or '' }}</textarea></div><div class="form-group"><label>Social Bar / Sticky Ad Code</label><textarea name="social_bar_code" rows="4">{{ ad_settings.social_bar_code or '' }}</textarea></div><div class="form-group"><label>ব্যানার বিজ্ঞাপন কোড (Banner Ad)</label><textarea name="banner_ad_code" rows="4">{{ ad_settings.banner_ad_code or '' }}</textarea></div><div class="form-group"><label>নেটিভ ব্যানার বিজ্ঞাপন (Native Banner)</label><textarea name="native_banner_code" rows="4">{{ ad_settings.native_banner_code or '' }}</textarea></div><button type="submit">Save Ad Codes</button></form>
  <hr class="section-divider">
  <h2>Add New Content (Manual)</h2>
  <form method="post" action="{{ url_for('admin') }}">
    <div class="form-group"><label>Title (Required):</label><input type="text" name="title" required /></div>
    <div class="form-group"><label>Content Type:</label><select name="content_type" id="content_type" onchange="toggleFields()"><option value="movie">Movie</option><option value="series">TV/Web Series</option></select></div>
    <div id="movie_fields">
        <div class="link-section"><h3>Watch Online</h3><div class="form-group"><label>Watch Link (Embed URL):</label><input type="url" name="watch_link" /></div></div>
        <div class="link-section"><h3>Download Links (Manual)</h3><div class="form-group"><label>1080p Download Link:</label><input type="url" name="download_link_1080p" /></div><div class="form-group"><label>720p Download Link:</label><input type="url" name="download_link_720p" /></div><div class="form-group"><label>480p Download Link:</label><input type="url" name="download_link_480p" /></div></div>
        <div class="link-section"><h3>TeraBox Links</h3><div class="form-group"><label>1080p TeraBox Link:</label><input type="url" name="terabox_link_1080p" /></div><div class="form-group"><label>720p TeraBox Link:</label><input type="url" name="terabox_link_720p" /></div><div class="form-group"><label>480p TeraBox Link:</label><input type="url" name="terabox_link_480p" /></div></div>
        <div class="link-section"><h3>Telegram Files</h3><p style="color: #aaa; font-size: 0.9em;">(Manual entry for Telegram files)</p><div id="telegram_files_container"></div><button type="button" onclick="addTelegramFileField()" class="add-btn">Add Telegram File</button></div>
    </div>
    <div id="episode_fields" style="display: none;"><h3>Episodes</h3><div id="episodes_container"></div><button type="button" onclick="addEpisodeField()" class="add-btn">Add Episode</button></div>
    <hr style="margin: 20px 0;"><button type="submit">Add Content</button>
  </form>
  <hr class="section-divider">
  <h2>Manage Content</h2>
  <form method="GET" action="{{ url_for('admin') }}" style="padding: 15px; background: #252525; display: flex; gap: 10px; align-items: center;">
    <input type="search" name="search" placeholder="Search by title..." value="{{ search_query or '' }}" style="flex-grow: 1;"><button type="submit">Search</button>
    {% if search_query %}<a href="{{ url_for('admin') }}" class="clear-btn">Clear</a>{% endif %}
  </form>
  <table><thead><tr><th>Title</th><th>Type</th><th>Actions</th></tr></thead><tbody>
    {% for movie in content_list %}<tr><td>{{ movie.title }}</td><td>{{ movie.type | title }}</td><td class="action-buttons"><a href="{{ url_for('edit_movie', movie_id=movie._id) }}" class="edit-btn">Edit</a><button class="delete-btn" onclick="confirmDelete('{{ movie._id }}', '{{ movie.title }}')">Delete</button></td></tr>
    {% else %}<tr><td colspan="3" style="text-align: center;">No content found.</td></tr>{% endfor %}
  </tbody></table>
  <hr class="section-divider">
  <h2>User Feedback / Reports</h2>
  {% if feedback_list %}<table><thead><tr><th>Date</th><th>Type</th><th>Title</th><th>Message</th><th>Email</th><th>Action</th></tr></thead><tbody>{% for item in feedback_list %}<tr><td style="min-width: 150px;">{{ item.timestamp.strftime('%Y-%m-%d %H:%M') }}</td><td>{{ item.type }}</td><td>{{ item.content_title }}</td><td style="white-space: pre-wrap; min-width: 300px;">{{ item.message }}</td><td>{{ item.email or 'N/A' }}</td><td><a href="{{ url_for('delete_feedback', feedback_id=item._id) }}" class="delete-btn" onclick="return confirm('Delete this feedback?');">Delete</a></td></tr>{% endfor %}</tbody></table>
  {% else %}<p>No new feedback or reports.</p>{% endif %}
  <script>
    function confirmDelete(id, title) { if (confirm('Delete "' + title + '"?')) window.location.href = '/delete_movie/' + id; }
    function toggleFields() { var isSeries = document.getElementById('content_type').value === 'series'; document.getElementById('episode_fields').style.display = isSeries ? 'block' : 'none'; document.getElementById('movie_fields').style.display = isSeries ? 'none' : 'block'; }
    function addTelegramFileField() { const c = document.getElementById('telegram_files_container'); const d = document.createElement('div'); d.className = 'dynamic-item'; d.innerHTML = `<div class="form-group"><label>Quality (e.g., 720p):</label><input type="text" name="telegram_quality[]" required /></div><div class="form-group"><label>Message ID:</label><input type="number" name="telegram_message_id[]" required /></div><button type="button" onclick="this.parentElement.remove()" class="delete-btn">Remove</button>`; c.appendChild(d); }
    function addEpisodeField() { const c = document.getElementById('episodes_container'); const d = document.createElement('div'); d.className = 'dynamic-item'; d.innerHTML = `<div class="form-group"><label>Season:</label><input type="number" name="episode_season[]" value="1" required /></div><div class="form-group"><label>Episode:</label><input type="number" name="episode_number[]" required /></div><div class="form-group"><label>Title:</label><input type="text" name="episode_title[]" /></div><hr><p><b>Provide ONE:</b></p><div class="form-group"><label>Telegram Message ID:</label><input type="number" name="episode_message_id[]" /></div><p><b>OR</b> Watch Link:</p><div class="form-group"><label>Watch Link (Embed):</label><input type="url" name="episode_watch_link[]" /></div><button type="button" onclick="this.parentElement.remove()" class="delete-btn">Remove</button>`; c.appendChild(d); }
    document.addEventListener('DOMContentLoaded', toggleFields);
  </script>
</body></html>
"""

edit_html = """
<!DOCTYPE html>
<html><head><title>Edit Content - MovieZone</title><meta name="viewport" content="width=device-width, initial-scale=1" /><style>
:root { --netflix-red: #E50914; --netflix-black: #141414; --dark-gray: #222; --light-gray: #333; --text-light: #f5f5f5; }
body { font-family: 'Roboto', sans-serif; background: var(--netflix-black); color: var(--text-light); padding: 20px; }
h2, h3 { font-family: 'Bebas Neue', sans-serif; color: var(--netflix-red); } h2 { font-size: 2.5rem; margin-bottom: 20px; } h3 { font-size: 1.5rem; margin: 20px 0 10px 0;}
form { max-width: 800px; margin: 0 auto 40px auto; background: var(--dark-gray); padding: 25px; border-radius: 8px;}
.form-group { margin-bottom: 15px; } .form-group label { display: block; margin-bottom: 8px; font-weight: bold; }
input, textarea, select { width: 100%; padding: 12px; border-radius: 4px; border: 1px solid var(--light-gray); font-size: 1rem; background: var(--light-gray); color: var(--text-light); box-sizing: border-box; }
input[type="checkbox"] { width: auto; margin-right: 10px; transform: scale(1.2); } textarea { resize: vertical; min-height: 100px; }
button[type="submit"], .add-btn { background: var(--netflix-red); color: white; font-weight: 700; cursor: pointer; border: none; padding: 12px 25px; border-radius: 4px; font-size: 1rem; }
.back-to-admin { display: inline-block; margin-bottom: 20px; color: var(--netflix-red); text-decoration: none; font-weight: bold; }
.dynamic-item { border: 1px solid var(--light-gray); padding: 15px; margin-bottom: 15px; border-radius: 5px; } .delete-btn { background: #dc3545; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
.link-section { border-left: 3px solid var(--netflix-red); padding-left: 15px; margin-top: 20px;}
</style><link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
<body>
  <a href="{{ url_for('admin') }}" class="back-to-admin">← Back to Admin</a>
  <h2>Edit: {{ movie.title }}</h2>
  <form method="post">
    <div class="form-group"><label>Title:</label><input type="text" name="title" value="{{ movie.title }}" required /></div>
    <div class="form-group"><label>Poster URL:</label><input type="url" name="poster" value="{{ movie.poster or '' }}" /></div>
    <div class="form-group"><label>Backdrop URL:</label><input type="url" name="backdrop" value="{{ movie.backdrop or '' }}" /></div>
    <div class="form-group"><label>Overview:</label><textarea name="overview">{{ movie.overview or '' }}</textarea></div>
    <div class="form-group"><label>Genres (comma separated):</label><input type="text" name="genres" value="{{ movie.genres|join(', ') if movie.genres else '' }}" /></div>
    <div class="form-group"><label>Languages (comma separated):</label><input type="text" name="languages" value="{{ movie.languages|join(', ') if movie.languages else '' }}" placeholder="e.g. Hindi, English, Bangla" /></div>
    <div class="form-group"><label>Poster Badge:</label><input type="text" name="poster_badge" value="{{ movie.poster_badge or '' }}" /></div>
    <div class="form-group"><label>Content Type:</label><select name="content_type" id="content_type" onchange="toggleFields()"><option value="movie" {% if movie.type == 'movie' %}selected{% endif %}>Movie</option><option value="series" {% if movie.type == 'series' %}selected{% endif %}>TV/Web Series</option></select></div>
    <div id="movie_fields">
        <div class="link-section"><h3>Watch Online</h3><div class="form-group"><label>Watch Link (Embed URL):</label><input type="url" name="watch_link" value="{{ movie.watch_link or '' }}" /></div></div>
        <div class="link-section"><h3>Download Links</h3><div class="form-group"><label>1080p Link:</label><input type="url" name="download_link_1080p" value="{% for l in movie.links %}{% if l.quality == '1080p' %}{{ l.url }}{% endif %}{% endfor %}" /></div><div class="form-group"><label>720p Link:</label><input type="url" name="download_link_720p" value="{% for l in movie.links %}{% if l.quality == '720p' %}{{ l.url }}{% endif %}{% endfor %}" /></div><div class="form-group"><label>480p Link:</label><input type="url" name="download_link_480p" value="{% for l in movie.links %}{% if l.quality == '480p' %}{{ l.url }}{% endif %}{% endfor %}" /></div></div>
        <div class="link-section"><h3>TeraBox Links</h3><div class="form-group"><label>1080p TeraBox:</label><input type="url" name="terabox_link_1080p" value="{% for l in movie.terabox_links %}{% if l.quality == '1080p' %}{{ l.url }}{% endif %}{% endfor %}" /></div><div class="form-group"><label>720p TeraBox:</label><input type="url" name="terabox_link_720p" value="{% for l in movie.terabox_links %}{% if l.quality == '720p' %}{{ l.url }}{% endif %}{% endfor %}" /></div><div class="form-group"><label>480p TeraBox:</label><input type="url" name="terabox_link_480p" value="{% for l in movie.terabox_links %}{% if l.quality == '480p' %}{{ l.url }}{% endif %}{% endfor %}" /></div></div>
        <div class="link-section"><h3>Telegram Files</h3><div id="telegram_files_container">{% if movie.type == 'movie' and movie.files %}{% for file in movie.files %}<div class="dynamic-item"><div class="form-group"><label>Quality:</label><input type="text" name="telegram_quality[]" value="{{ file.quality }}" required /></div><div class="form-group"><label>Message ID:</label><input type="number" name="telegram_message_id[]" value="{{ file.message_id }}" required /></div><button type="button" onclick="this.parentElement.remove()" class="delete-btn">Remove</button></div>{% endfor %}{% endif %}</div><button type="button" onclick="addTelegramFileField()" class="add-btn">Add File</button></div>
    </div>
    <div id="episode_fields" style="display: none;"><h3>Episodes</h3><div id="episodes_container">{% if movie.type == 'series' and movie.episodes %}{% for ep in movie.episodes | sort(attribute='episode_number') | sort(attribute='season') %}<div class="dynamic-item"><div class="form-group"><label>Season:</label><input type="number" name="episode_season[]" value="{{ ep.season or 1 }}" required /></div><div class="form-group"><label>Episode:</label><input type="number" name="episode_number[]" value="{{ ep.episode_number }}" required /></div><div class="form-group"><label>Title:</label><input type="text" name="episode_title[]" value="{{ ep.title or '' }}" /></div><hr><p><b>Provide ONE:</b></p><div class="form-group"><label>Telegram Msg ID:</label><input type="number" name="episode_message_id[]" value="{{ ep.message_id or '' }}" /></div><p><b>OR</b> Watch Link:</p><div class="form-group"><label>Watch Link:</label><input type="url" name="episode_watch_link[]" value="{{ ep.watch_link or '' }}" /></div><button type="button" onclick="this.parentElement.remove()" class="delete-btn">Remove</button></div>{% endfor %}{% endif %}</div><button type="button" onclick="addEpisodeField()" class="add-btn">Add Episode</button></div>
    <hr style="margin: 20px 0;">
    <div class="form-group"><input type="checkbox" name="is_trending" value="true" {% if movie.is_trending %}checked{% endif %}><label style="display: inline-block;">Is Trending?</label></div>
    <div class="form-group"><input type="checkbox" name="is_coming_soon" value="true" {% if movie.is_coming_soon %}checked{% endif %}><label style="display: inline-block;">Is Coming Soon?</label></div>
    <button type="submit">Update Content</button>
  </form>
  <script>
    function toggleFields() { var isSeries = document.getElementById('content_type').value === 'series'; document.getElementById('episode_fields').style.display = isSeries ? 'block' : 'none'; document.getElementById('movie_fields').style.display = isSeries ? 'none' : 'block'; }
    function addTelegramFileField() { const c = document.getElementById('telegram_files_container'); const d = document.createElement('div'); d.className = 'dynamic-item'; d.innerHTML = `<div class="form-group"><label>Quality (e.g., 720p):</label><input type="text" name="telegram_quality[]" required /></div><div class="form-group"><label>Message ID:</label><input type="number" name="telegram_message_id[]" required /></div><button type="button" onclick="this.parentElement.remove()" class="delete-btn">Remove</button>`; c.appendChild(d); }
    function addEpisodeField() { const c = document.getElementById('episodes_container'); const d = document.createElement('div'); d.className = 'dynamic-item'; d.innerHTML = `<div class="form-group"><label>Season:</label><input type="number" name="episode_season[]" value="1" required /></div><div class="form-group"><label>Episode:</label><input type="number" name="episode_number[]" required /></div><div class="form-group"><label>Title:</label><input type="text" name="episode_title[]" /></div><hr><p><b>Provide ONE:</b></p><div class="form-group"><label>Telegram Message ID:</label><input type="number" name="episode_message_id[]" /></div><p><b>OR</b> Watch Link:</p><div class="form-group"><label>Watch Link (Embed):</label><input type="url" name="episode_watch_link[]" /></div><button type="button" onclick="this.parentElement.remove()" class="delete-btn">Remove Episode</button>`; c.appendChild(d); }
    document.addEventListener('DOMContentLoaded', toggleFields);
  </script>
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
# --- Helper Functions ---
# ======================================================================
def parse_filename(filename):
    LANGUAGE_MAP = {'hindi': 'Hindi', 'hin': 'Hindi', 'english': 'English', 'eng': 'English', 'bengali': 'Bengali', 'bangla': 'Bangla', 'ben': 'Bengali', 'tamil': 'Tamil', 'tam': 'Tamil', 'telugu': 'Telugu', 'tel': 'Telugu', 'kannada': 'Kannada', 'kan': 'Kannada', 'malayalam': 'Malayalam', 'mal': 'Malayalam', 'dual audio': ['Hindi', 'English'], 'multi audio': ['Multi Audio']}
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
        title, season_num, episode_num = series_match.group(1).strip(), int(series_match.group(2)), int(series_match.group(3))
        title = re.sub(r'\[.*?\]|\(.*?\)|(?i)\b(season|s)\s*\d+\s*$', '', title).strip()
        return {'type': 'series', 'title': title.title(), 'season': season_num, 'episode': episode_num, 'languages': languages}
    year_match = re.search(r'\(?(19[5-9]\d|20\d{2})\)?', cleaned_name)
    year, title = (year_match.group(1), cleaned_name[:year_match.start()].strip()) if year_match else (None, cleaned_name)
    junk_patterns = [r'\b(1080p|720p|480p|2160p|4k|uhd|web-?dl|webrip|brrip|bluray|dvdrip|hdrip|hdcam|camrip|x264|x265|hevc|avc|aac|ac3|dts|5\.1|7\.1|complete|pack|final|uncut|extended|remastered)\b', r'\[.*?\]', r'\(.*?\)']
    for lang_key in LANGUAGE_MAP.keys(): title = re.sub(r'(?i)\b' + lang_key + r'\b', '', title)
    for pattern in junk_patterns: title = re.sub(pattern, '', title, flags=re.I)
    title = re.sub(r'\s+', ' ', title).strip()
    return {'type': 'movie', 'title': title.title(), 'year': year, 'languages': languages}

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
        return {"tmdb_id": tmdb_id, "title": res.get("title") or res.get("name"), "poster": f"https://image.tmdb.org/t/p/w500{res.get('poster_path')}" if res.get('poster_path') else None, "backdrop": f"https://image.tmdb.org/t/p/w1280{res.get('backdrop_path')}" if res.get('backdrop_path') else None, "overview": res.get("overview"), "release_date": res.get("release_date") or res.get("first_air_date"), "genres": [g['name'] for g in res.get("genres", [])], "vote_average": res.get("vote_average")}
    except requests.RequestException as e:
        print(f"TMDb API error for '{title}': {e}")
    return None

def extract_links_from_message(text):
    watch_link, download_links = None, []
    # Adjust these patterns based on your link generator bot's message format
    watch_match = re.search(r'(https?://[^\s]+(?:embed|watch)[^\s]*)', text, re.IGNORECASE)
    if watch_match: watch_link = watch_match.group(1)
    urls = re.findall(r'https?://[^\s]+', text)
    for url in urls:
        if watch_link and url in watch_link: continue
        quality = "1080p" if "1080p" in url or "1080" in url else "720p" if "720p" in url or "720" in url else "480p" if "480p" in url or "480" in url else "HD"
        download_links.append({"quality": quality, "url": url})
    return {"watch_link": watch_link, "download_links": download_links}
    
def process_movie_list(movie_list):
    for item in movie_list:
        if '_id' in item: item['_id'] = str(item['_id'])
    return movie_list

# ======================================================================
# --- Main Flask Routes ---
# ======================================================================
@app.route('/')
def home():
    query = request.args.get('q')
    if query:
        movies_list = list(movies.find({"$text": {"$search": query}}))
        return render_template_string(index_html, movies=process_movie_list(movies_list), query=f'Results for "{query}"', is_full_page_list=True)
    limit = 12
    context = {"trending_movies": process_movie_list(list(movies.find({"is_trending": True, "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))), "latest_movies": process_movie_list(list(movies.find({"type": "movie", "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))), "latest_series": process_movie_list(list(movies.find({"type": "series", "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))), "coming_soon_movies": process_movie_list(list(movies.find({"is_coming_soon": True}).sort('_id', -1).limit(limit))), "recently_added": process_movie_list(list(movies.find({"is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(6))), "is_full_page_list": False, "query": ""}
    return render_template_string(index_html, **context)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    try:
        movie = movies.find_one({"_id": ObjectId(movie_id)})
        if not movie: return "Content not found", 404
        related_movies = []
        if movie.get("genres"):
            related_movies = list(movies.find({"genres": {"$in": movie["genres"]}, "_id": {"$ne": ObjectId(movie_id)}}).sort("_id", -1).limit(12))
        trailer_key = None
        if movie.get("tmdb_id") and TMDB_API_KEY:
            tmdb_type = "tv" if movie.get("type") == "series" else "movie"
            video_url = f"https://api.themoviedb.org/3/{tmdb_type}/{movie['tmdb_id']}/videos?api_key={TMDB_API_KEY}"
            try:
                video_res = requests.get(video_url, timeout=3).json()
                for v in video_res.get("results", []):
                    if v.get('type') == 'Trailer' and v.get('site') == 'YouTube':
                        trailer_key = v.get('key'); break
            except requests.RequestException: pass
        return render_template_string(detail_html, movie=movie, trailer_key=trailer_key, related_movies=process_movie_list(related_movies))
    except Exception: return "Content not found", 404

@app.route('/watch/<movie_id>')
def watch_movie(movie_id):
    try:
        movie = movies.find_one({"_id": ObjectId(movie_id)})
        if not movie or not movie.get("watch_link"): return "Content not found.", 404
        return render_template_string(watch_html, watch_link=movie["watch_link"], title=movie["title"])
    except Exception: return "An error occurred.", 500

def render_full_list(content_list, title):
    return render_template_string(index_html, movies=process_movie_list(content_list), query=title, is_full_page_list=True)

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

# ======================================================================
# --- Admin and Webhook Routes ---
# ======================================================================
@app.route('/admin/update_backdrops')
@requires_auth
def update_all_backdrops():
    try:
        movies_to_update = list(movies.find({"$or": [{"backdrop": {"$exists": False}}, {"backdrop": None}, {"backdrop": ""}]}))
        updated_count, log_messages = 0, []
        for movie in movies_to_update:
            if not movie.get('tmdb_id'):
                log_messages.append(f"Skipping '{movie.get('title')}' - no tmdb_id.")
                continue
            try:
                tmdb_id, content_type = movie['tmdb_id'], movie.get('type', 'movie')
                tmdb_type = "tv" if content_type == "series" else "movie"
                detail_url = f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
                res = requests.get(detail_url, timeout=5).json()
                backdrop_path = res.get('backdrop_path')
                if backdrop_path:
                    backdrop_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}"
                    movies.update_one({"_id": movie["_id"]}, {"$set": {"backdrop": backdrop_url}})
                    log_messages.append(f"Updated backdrop for: {movie.get('title')}")
                    updated_count += 1
                else:
                    log_messages.append(f"No backdrop found on TMDB for: {movie.get('title')}")
            except Exception as e:
                log_messages.append(f"Error updating '{movie.get('title')}': {e}")
        final_message = f"<h1>Update Complete!</h1><p>{updated_count} out of {len(movies_to_update)} movies have been updated.</p><a href='/admin'>Back to Admin Panel</a><hr><h3>Logs:</h3><pre>" + "\n".join(log_messages) + "</pre>"
        return final_message
    except Exception as e:
        return f"<h1>An error occurred!</h1><p>{e}</p>"

@app.route('/admin', methods=["GET", "POST"])
@requires_auth
def admin():
    if request.method == "POST":
        content_type = request.form.get("content_type", "movie")
        tmdb_data = get_tmdb_details_from_api(request.form.get("title"), content_type) or {}
        movie_data = {**tmdb_data, "title": request.form.get("title"), "type": content_type, "is_trending": False, "is_coming_soon": False, "links": [], "terabox_links": [], "files": [], "episodes": [], "languages": []}
        if content_type == "movie":
            movie_data["watch_link"] = request.form.get("watch_link", "").strip()
            links = [{"quality": q.replace("p","")+"p", "url": u} for q, u in [("1080p", request.form.get("download_link_1080p")), ("720p", request.form.get("download_link_720p")), ("480p", request.form.get("download_link_480p"))] if u]
            terabox_links = [{"quality": q.replace("p","")+"p", "url": u} for q, u in [("1080p", request.form.get("terabox_link_1080p")), ("720p", request.form.get("terabox_link_720p")), ("480p", request.form.get("terabox_link_480p"))] if u]
            files = [{"quality": q, "message_id": int(mid)} for q, mid in zip(request.form.getlist('telegram_quality[]'), request.form.getlist('telegram_message_id[]')) if q and mid]
            movie_data.update({"links": links, "terabox_links": terabox_links, "files": files})
        else:
            episodes = [{"season": int(s), "episode_number": int(en), "title": et, "watch_link": ewl or None, "message_id": int(emid) if emid else None} for s, en, et, ewl, emid in zip(request.form.getlist('episode_season[]'), request.form.getlist('episode_number[]'), request.form.getlist('episode_title[]'), request.form.getlist('episode_watch_link[]'), request.form.getlist('episode_message_id[]')) if en]
            movie_data["episodes"] = episodes
        movies.insert_one(movie_data)
        return redirect(url_for('admin'))
    search_query = request.args.get('search', '').strip()
    query_filter = {"$text": {"$search": search_query}} if search_query else {}
    content_list = process_movie_list(list(movies.find(query_filter).sort('_id', -1)))
    feedback_list = process_movie_list(list(feedback.find().sort('timestamp', -1)))
    ad_settings = settings.find_one() or {}
    return render_template_string(admin_html, content_list=content_list, feedback_list=feedback_list, search_query=search_query, ad_settings=ad_settings)

@app.route('/admin/save_ads', methods=['POST'])
@requires_auth
def save_ads():
    ad_codes = {"popunder_code": request.form.get("popunder_code"), "social_bar_code": request.form.get("social_bar_code"), "banner_ad_code": request.form.get("banner_ad_code"), "native_banner_code": request.form.get("native_banner_code")}
    settings.update_one({}, {"$set": ad_codes}, upsert=True)
    return redirect(url_for('admin'))

@app.route('/edit_movie/<movie_id>', methods=["GET", "POST"])
@requires_auth
def edit_movie(movie_id):
    movie_obj = movies.find_one({"_id": ObjectId(movie_id)})
    if not movie_obj: return "Movie not found", 404
    if request.method == "POST":
        content_type = request.form.get("content_type", "movie")
        update_data = {"title": request.form.get("title"), "type": content_type, "is_trending": request.form.get("is_trending") == "true", "is_coming_soon": request.form.get("is_coming_soon") == "true", "poster": request.form.get("poster", "").strip(), "backdrop": request.form.get("backdrop", "").strip(), "overview": request.form.get("overview", "").strip(), "genres": [g.strip() for g in request.form.get("genres", "").split(',') if g.strip()], "languages": [lang.strip() for lang in request.form.get("languages", "").split(',') if lang.strip()], "poster_badge": request.form.get("poster_badge", "").strip() or None}
        if content_type == "movie":
            update_data["watch_link"] = request.form.get("watch_link", "").strip()
            update_data["links"] = [{"quality": q.replace("p","")+"p", "url": u} for q, u in [("1080p", request.form.get("download_link_1080p")), ("720p", request.form.get("download_link_720p")), ("480p", request.form.get("download_link_480p"))] if u]
            update_data["terabox_links"] = [{"quality": q.replace("p","")+"p", "url": u} for q, u in [("1080p", request.form.get("terabox_link_1080p")), ("720p", request.form.get("terabox_link_720p")), ("480p", request.form.get("terabox_link_480p"))] if u]
            update_data["files"] = [{"quality": q, "message_id": int(mid)} for q, mid in zip(request.form.getlist('telegram_quality[]'), request.form.getlist('telegram_message_id[]')) if q and mid]
            movies.update_one({"_id": ObjectId(movie_id)}, {"$unset": {"episodes": ""}})
        else:
            update_data["episodes"] = [{"season": int(s), "episode_number": int(en), "title": et, "watch_link": ewl or None, "message_id": int(emid) if emid else None} for s, en, et, ewl, emid in zip(request.form.getlist('episode_season[]'), request.form.getlist('episode_number[]'), request.form.getlist('episode_title[]'), request.form.getlist('episode_watch_link[]'), request.form.getlist('episode_message_id[]')) if en]
            movies.update_one({"_id": ObjectId(movie_id)}, {"$unset": {"links": "", "terabox_links": "", "watch_link": "", "files": ""}})
        movies.update_one({"_id": ObjectId(movie_id)}, {"$set": update_data})
        return redirect(url_for('admin'))
    return render_template_string(edit_html, movie=movie_obj)

@app.route('/delete_movie/<movie_id>')
@requires_auth
def delete_movie(movie_id):
    movies.delete_one({"_id": ObjectId(movie_id)})
    return redirect(url_for('admin'))

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        feedback.insert_one({"type": request.form.get("type"), "content_title": request.form.get("content_title"), "message": request.form.get("message"), "email": request.form.get("email", "").strip(), "reported_content_id": request.form.get("reported_content_id"), "timestamp": datetime.utcnow()})
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
    if not data or 'channel_post' not in data:
        return jsonify(status='ok', reason='not_a_channel_post')

    post = data['channel_post']
    chat_id_str = str(post['chat']['id'])

    # --- লিঙ্ক ক্যাপচার চ্যানেল থেকে লিঙ্ক সংগ্রহ ---
    if chat_id_str == LINK_CAPTURE_CHANNEL_ID:
        message_text = post.get('text') or post.get('caption', '')
        title_match = re.search(r"Title:\s*(.+)", message_text)
        if title_match:
            title = title_match.group(1).strip()
            links = extract_links_from_message(message_text)
            update_result = movies.update_one(
                {"title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}},
                {"$set": {"watch_link": links['watch_link'], "links": links['download_links']}}
            )
            if update_result.modified_count > 0: print(f"Successfully updated links for: {title}")
            else: print(f"Could not find movie to update links for: {title}")
        return jsonify(status='ok', reason='link_capture_processed')

    # --- অ্যাডমিন চ্যানেল থেকে ফাইল আপলোড হ্যান্ডেল করা ---
    if chat_id_str == ADMIN_CHANNEL_ID:
        file_data = post.get('video') or post.get('document')
        if not (file_data and file_data.get('file_name')): return jsonify(status='ok', reason='no_file_in_post')
        
        filename = file_data.get('file_name')
        parsed_info = parse_filename(filename)
        if not (parsed_info and parsed_info.get('title')): return jsonify(status='ok', reason='parse_failed')

        tmdb_data = get_tmdb_details_from_api(parsed_info['title'], parsed_info['type'], parsed_info.get('year'))
        if not tmdb_data: return jsonify(status='ok', reason='no_tmdb_data')

        quality = (re.search(r'(\d{3,4})p', filename, re.I).group(1) + "p") if re.search(r'(\d{3,4})p', filename, re.I) else "HD"
        db_entry = {**tmdb_data, "type": parsed_info['type'], "languages": parsed_info.get('languages', [])}
        movies.update_one({"tmdb_id": tmdb_data['tmdb_id']}, {"$set": db_entry, "$push": {"files": {"quality": quality, "message_id": post['message_id']}}}, upsert=True)
        print(f"Initial entry created/updated for: {tmdb_data['title']}")

        try:
            file_id = file_data['file_id']
            file_path_res = requests.get(f"{TELEGRAM_API_URL}/getFile", params={'file_id': file_id}).json()
            if not file_path_res.get('ok'):
                print(f"Failed to get file path: {file_path_res}")
                return jsonify(status='ok')
            
            file_path = file_path_res['result']['file_path']
            telegram_file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            
            with requests.get(telegram_file_url, stream=True) as r:
                r.raise_for_status()
                temp_file_path = f"/tmp/{filename.replace('/', '_')}"
                with open(temp_file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): f.write(chunk)
            print(f"File downloaded to: {temp_file_path}")

            with open(temp_file_path, 'rb') as f_to_upload:
                upload_url = f"{TELEGRAM_API_URL}/sendDocument"
                files = {'document': (filename, f_to_upload)}
                caption_text = f"Title: {tmdb_data['title']}"
                payload = {'chat_id': f"@{LINK_GENERATOR_BOT_USERNAME}", 'caption': caption_text}
                res = requests.post(upload_url, data=payload, files=files, timeout=60)
                if res.json().get('ok'): print(f"Successfully sent file to @{LINK_GENERATOR_BOT_USERNAME}")
                else: print(f"Failed to send file to bot: {res.text}")

            os.remove(temp_file_path)
            print(f"Temporary file removed: {temp_file_path}")

        except Exception as e: print(f"An error occurred in the file download/upload process: {e}")
        return jsonify(status='ok', reason='admin_post_processed')

    # --- /start কমান্ড হ্যান্ডেল করা ---
    if 'message' in data:
        message, chat_id, text = data['message'], data['message']['chat']['id'], data['message'].get('text', '')
        if text.startswith('/start'):
            parts = text.split()
            if len(parts) > 1:
                try:
                    payload_parts = parts[1].split('_')
                    content = movies.find_one({"_id": ObjectId(payload_parts[0])})
                    if not content: return requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "Content not found."})
                    msg_id_to_copy = None
                    if content.get('type') == 'series' and len(payload_parts) == 3:
                        s, e = int(payload_parts[1]), int(payload_parts[2])
                        episode = next((ep for ep in content.get('episodes', []) if ep.get('season') == s and ep.get('episode_number') == e), None)
                        if episode: msg_id_to_copy = episode.get('message_id')
                    elif content.get('type') == 'movie' and len(payload_parts) == 2:
                        file = next((f for f in content.get('files', []) if f.get('quality') == payload_parts[1]), None)
                        if file: msg_id_to_copy = file.get('message_id')
                    if msg_id_to_copy:
                        res = requests.post(f"{TELEGRAM_API_URL}/copyMessage", json={'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': msg_id_to_copy}).json()
                        if res.get('ok'):
                            scheduler.add_job(func=delete_message_after_delay, trigger='date', run_date=datetime.now() + timedelta(minutes=30), args=[chat_id, res['result']['message_id']], id=f'del_{chat_id}_{res["result"]["message_id"]}', replace_existing=True)
                    else: requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "Requested file not found."})
                except Exception as e: requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "An error occurred."})
            else: requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "Welcome to our website. Please browse and select content."})
    return jsonify(status='ok')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
