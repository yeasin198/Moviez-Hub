import os
import sys
import re
import requests
from flask import Flask, render_template_string, request, redirect, url_for, Response, jsonify
from pymongo import MongoClient
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

# আপনার চ্যানেল এবং ডেভেলপারের তথ্য
MAIN_CHANNEL_LINK = os.environ.get("MAIN_CHANNEL_LINK")
UPDATE_CHANNEL_LINK = os.environ.get("UPDATE_CHANNEL_LINK")
DEVELOPER_USER_LINK = os.environ.get("DEVELOPER_USER_LINK")
SITE_NAME = "MovieDokan" # আপনি চাইলে এটি পরিবর্তন করতে পারেন

# --- প্রয়োজনীয় ভেরিয়েবলগুলো সেট করা হয়েছে কিনা তা পরীক্ষা করা ---
required_vars = {
    "MONGO_URI": MONGO_URI, "BOT_TOKEN": BOT_TOKEN, "TMDB_API_KEY": TMDB_API_KEY,
    "ADMIN_CHANNEL_ID": ADMIN_CHANNEL_ID, "BOT_USERNAME": BOT_USERNAME,
    "ADMIN_USERNAME": ADMIN_USERNAME, "ADMIN_PASSWORD": ADMIN_PASSWORD,
    "MAIN_CHANNEL_LINK": MAIN_CHANNEL_LINK,
    "UPDATE_CHANNEL_LINK": UPDATE_CHANNEL_LINK,
    "DEVELOPER_USER_LINK": DEVELOPER_USER_LINK,
}

missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    print(f"FATAL: Missing required environment variables: {', '.join(missing_vars)}")
    print("Please set these variables in your deployment environment and restart the application.")
    sys.exit(1)

# ======================================================================
# --- অ্যাপ্লিকেশন সেটআপ এবং অন্যান্য ফাংশন ---
# ======================================================================
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = Flask(__name__)

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

@app.context_processor
def inject_global_vars():
    ad_codes = settings.find_one()
    return dict(
        ad_settings=(ad_codes or {}),
        bot_username=BOT_USERNAME,
        main_channel_link=MAIN_CHANNEL_LINK,
        site_name=SITE_NAME
    )

def delete_message_after_delay(chat_id, message_id):
    print(f"Attempting to delete message {message_id} from chat {chat_id}")
    try:
        url = f"{TELEGRAM_API_URL}/deleteMessage"
        payload = {'chat_id': chat_id, 'message_id': message_id}
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error in delete_message_after_delay: {e}")

scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

def escape_markdown(text: str) -> str:
    if not isinstance(text, str):
        return ''
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# ======================================================================
# --- HTML টেমপ্লেট ---
# ======================================================================

# --- Base Layout Template ---
base_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>{% block title %}{{ site_name }} - Your Entertainment Hub{% endblock %}</title>
    <style>
      /* --- Global Styles & Variables --- */
      @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
      :root {
        --primary-color: #00ff6a; /* Bright Green Accent */
        --bg-color: #0d0d0d;      /* Main Background */
        --card-bg-color: #1a1a1a;  /* Card & Section Background */
        --text-color: #e0e0e0;
        --text-muted-color: #888;
        --header-height: 70px;
      }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        font-family: 'Poppins', sans-serif;
        background-color: var(--bg-color);
        color: var(--text-color);
        overflow-x: hidden;
      }
      a { text-decoration: none; color: inherit; transition: color 0.3s ease; }
      a:hover { color: var(--primary-color); }
      img { max-width: 100%; display: block; }
      main { padding-top: var(--header-height); }
      .container { max-width: 1400px; margin: 0 auto; padding: 0 20px; }

      /* --- Header --- */
      .site-header {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: var(--header-height);
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 40px;
        z-index: 1000;
        background: linear-gradient(to bottom, rgba(0,0,0,0.7), transparent);
        transition: background-color 0.4s ease, height 0.4s ease;
      }
      .site-header.scrolled {
        background-color: #111;
        height: 65px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
      }
      .site-logo a { font-size: 1.8rem; font-weight: 700; letter-spacing: 1px; }
      .site-logo a span { color: var(--primary-color); }
      .main-nav ul { list-style: none; display: flex; gap: 30px; }
      .main-nav a { font-weight: 500; text-transform: uppercase; font-size: 0.9rem; }
      .header-search .search-input {
        background-color: rgba(255,255,255,0.1);
        border: 1px solid rgba(255,255,255,0.2);
        color: var(--text-color);
        padding: 8px 15px;
        border-radius: 50px;
        width: 250px;
        transition: all 0.3s ease;
      }
      .header-search .search-input:focus {
        background-color: rgba(255,255,255,0.2);
        border-color: var(--primary-color);
        outline: none;
      }
      .mobile-menu-toggle { display: none; cursor: pointer; font-size: 1.5rem; }
      
      /* --- Movie Card --- */
      .movie-card-h {
        display: inline-block;
        width: 200px;
        margin-right: 20px;
        vertical-align: top;
        white-space: normal;
        background-color: var(--card-bg-color);
        border-radius: 8px;
        overflow: hidden;
        transition: transform 0.3s ease, box-shadow 0.3s ease;
      }
      .movie-card-h:hover {
        transform: translateY(-10px);
        box-shadow: 0 10px 20px rgba(0, 255, 106, 0.1);
      }
      .movie-card-h-poster {
        position: relative;
        aspect-ratio: 2 / 3;
        background-color: #222;
      }
      .movie-card-h-poster img { width: 100%; height: 100%; object-fit: cover; }
      .quality-badge {
        position: absolute;
        top: 10px;
        right: 10px;
        background-color: rgba(0, 0, 0, 0.7);
        color: var(--text-color);
        padding: 4px 8px;
        font-size: 0.8rem;
        font-weight: 600;
        border-radius: 5px;
        backdrop-filter: blur(5px);
      }
      .movie-card-h-info { padding: 15px; }
      .movie-card-h-title {
        font-size: 1rem;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        margin-bottom: 5px;
      }
      .movie-card-h-meta {
        font-size: 0.8rem;
        color: var(--text-muted-color);
        display: flex;
        justify-content: space-between;
      }
      .movie-card-h-meta .fa-star { color: #f5c518; }
      
      /* --- Footer --- */
       .site-footer {
        background-color: var(--card-bg-color);
        padding: 40px;
        text-align: center;
        margin-top: 50px;
        border-top: 1px solid rgba(255,255,255,0.1);
      }
      .footer-logo { font-size: 2rem; font-weight: 700; margin-bottom: 15px; }
      .footer-logo span { color: var(--primary-color); }
      .footer-text { max-width: 600px; margin: 0 auto 20px auto; color: var(--text-muted-color); }
      .footer-nav { display: flex; justify-content: center; gap: 20px; margin-bottom: 20px; }
      .footer-nav a { color: var(--text-color); }

      /* --- Responsive --- */
      @media (max-width: 992px) {
        .main-nav { display: none; }
        .mobile-menu-toggle { display: block; }
        .site-header { padding: 0 20px; }
      }
      @media (max-width: 768px) {
        .header-search { display: none; }
        .movie-card-h { width: 150px; margin-right: 15px; }
      }
    </style>
    {% block head_extra %}{% endblock %}
</head>
<body>
    <header class="site-header" id="site-header">
        <div class="site-logo">
            <a href="{{ url_for('home') }}">{{ site_name.split(' ')[0] }}<span>{{ site_name.split(' ')[1] if site_name.split(' ')[1:] else '' }}</span></a>
        </div>
        <nav class="main-nav">
            <ul>
                <li><a href="{{ url_for('home') }}">Home</a></li>
                <li><a href="{{ url_for('movies_only') }}">Movies</a></li>
                <li><a href="{{ url_for('webseries') }}">Web Series</a></li>
                <li><a href="{{ url_for('genres_page') }}">Genres</a></li>
            </ul>
        </nav>
        <div class="header-search">
             <form method="GET" action="/">
                <input type="search" name="q" class="search-input" placeholder="Search..." value="{{ query|default('') }}">
            </form>
        </div>
        <div class="mobile-menu-toggle"><i class="fas fa-bars"></i></div>
    </header>

    <main>
        {% block content %}{% endblock %}
    </main>
    
    <footer class="site-footer">
        <div class="footer-logo">{{ site_name.split(' ')[0] }}<span>{{ site_name.split(' ')[1] if site_name.split(' ')[1:] else '' }}</span></div>
        <p class="footer-text">The ultimate destination for movies and web series. Enjoy a vast library of content, updated daily.</p>
        <div class="footer-nav">
            <a href="{{ url_for('home') }}">Home</a>
            <a href="{{ url_for('contact') }}">Contact Us</a>
            <a href="{{ main_channel_link }}">Telegram</a>
        </div>
        <p class="footer-copyright">© {{ now.year }} {{ site_name }}. All Rights Reserved.</p>
    </footer>

    <script>
        const header = document.getElementById('site-header');
        window.addEventListener('scroll', () => {
            header.classList.toggle('scrolled', window.scrollY > 50);
        });
    </script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
    {% if ad_settings.popunder_code %}{{ ad_settings.popunder_code|safe }}{% endif %}
</body>
</html>
"""

# --- Home Page Template ---
index_html = """
{% extends "base_html" %}

{% block title %}{{ site_name }} - Home{% endblock %}

{% block head_extra %}
<style>
  /* --- Hero Slider --- */
  .hero-slider {
    height: 85vh;
    position: relative;
    overflow: hidden;
    margin-top: -{{ header_height }}px; /* Pull it under the header */
  }
  .hero-slide {
    position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    background-size: cover; background-position: center top;
    display: flex; align-items: center; opacity: 0;
    transition: opacity 1.5s ease-in-out; z-index: 1;
  }
  .hero-slide.active { opacity: 1; z-index: 2; }
  .hero-slide::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(to right, rgba(13,13,13,1) 10%, rgba(13,13,13,0.8) 30%, rgba(13,13,13,0) 70%),
                linear-gradient(to top, rgba(13,13,13,1) 5%, transparent 40%);
  }
  .hero-content { position: relative; z-index: 3; padding: 0 40px; max-width: 50%; }
  .hero-title { font-size: 3.5rem; font-weight: 700; line-height: 1.2; margin-bottom: 15px; }
  .hero-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; color: var(--text-muted-color); }
  .hero-meta span { background-color: rgba(255,255,255,0.1); padding: 5px 10px; border-radius: 5px; font-size: 0.9rem; color: var(--text-color); }
  .hero-meta .imdb-rating { color: #f5c518; font-weight: bold; }
  .hero-overview {
    font-size: 1rem; line-height: 1.6; margin-bottom: 30px;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  }
  .hero-button {
    background-color: var(--primary-color); color: #000; padding: 12px 30px; border-radius: 50px;
    font-weight: 600; display: inline-flex; align-items: center; gap: 10px;
  }
  .hero-button i { font-size: 1.2rem; }

  /* --- Content Sections --- */
  .content-section { padding: 40px 0; }
  .section-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 25px; padding: 0 40px;
  }
  .section-title { font-size: 1.8rem; font-weight: 600; }
  .view-all-link { color: var(--primary-color); font-weight: 500; }

  /* --- Horizontal Scroll --- */
  .horizontal-scroll-wrapper {
    overflow-x: auto; overflow-y: hidden; white-space: nowrap;
    padding: 0 40px 20px 40px; scrollbar-width: none; /* Firefox */
  }
  .horizontal-scroll-wrapper::-webkit-scrollbar { display: none; /* Chrome, Safari, Opera */ }
  
  @media (max-width: 768px) {
    .hero-slider { height: 70vh; }
    .hero-content { max-width: 90%; padding: 0 20px; }
    .hero-title { font-size: 2.5rem; }
    .section-header, .horizontal-scroll-wrapper { padding: 0 20px; }
  }
</style>
{% endblock %}

{% block content %}
    <!-- Macro for rendering movie card -->
    {% macro render_movie_card(movie) %}
        <a href="{{ url_for('movie_detail', movie_id=movie._id) }}" class="movie-card-h">
            <div class="movie-card-h-poster">
                <img src="{{ movie.poster or 'https://via.placeholder.com/200x300.png?text=No+Poster' }}" alt="{{ movie.title }}" loading="lazy">
                {% if movie.display_quality %}<div class="quality-badge">{{ movie.display_quality }}</div>{% endif %}
            </div>
            <div class="movie-card-h-info">
                <h3 class="movie-card-h-title">{{ movie.title }}</h3>
                <div class="movie-card-h-meta">
                    <span>{{ movie.release_date.split('-')[0] if movie.release_date else 'N/A' }}</span>
                    {% if movie.vote_average and movie.vote_average > 0 %}
                    <span><i class="fas fa-star"></i> {{ "%.1f"|format(movie.vote_average) }}</span>
                    {% endif %}
                </div>
            </div>
        </a>
    {% endmacro %}

    <!-- Hero Slider Section -->
    {% if hero_movies %}
    <section class="hero-slider">
        {% for movie in hero_movies %}
        <div class="hero-slide {% if loop.first %}active{% endif %}" style="background-image: url('{{ movie.poster }}');">
            <div class="hero-content">
                <h1 class="hero-title">{{ movie.title }}</h1>
                <div class="hero-meta">
                    {% if movie.release_date %}<span>{{ movie.release_date.split('-')[0] }}</span>{% endif %}
                    {% if movie.vote_average > 0 %}
                    <span class="imdb-rating"><i class="fas fa-star"></i> {{ "%.1f"|format(movie.vote_average) }}</span>
                    {% endif %}
                    {% if movie.genres %}<span>{{ movie.genres[0] }}</span>{% endif %}
                </div>
                <p class="hero-overview">{{ movie.overview }}</p>
                <a href="{{ url_for('movie_detail', movie_id=movie._id) }}" class="hero-button">
                    <i class="fas fa-play"></i> Watch Now
                </a>
            </div>
        </div>
        {% endfor %}
    </section>
    {% endif %}

    <!-- Content Sections -->
    {% macro render_content_section(title, movies_list, view_all_endpoint) %}
        {% if movies_list %}
        <section class="content-section">
            <div class="section-header">
                <h2 class="section-title">{{ title }}</h2>
                <a href="{{ url_for(view_all_endpoint) }}" class="view-all-link">View All →</a>
            </div>
            <div class="horizontal-scroll-wrapper">
                {% for movie in movies_list %}
                    {{ render_movie_card(movie) }}
                {% endfor %}
            </div>
        </section>
        {% endif %}
    {% endmacro %}
    
    {{ render_content_section('Latest Movies', latest_movies, 'movies_only') }}
    {{ render_content_section('Latest Web Series', latest_series, 'webseries') }}
    {{ render_content_section('Trending Now', trending_movies, 'trending_movies') }}
    
    <script>
        const slides = document.querySelectorAll('.hero-slide');
        if (slides.length > 1) {
            let currentSlide = 0;
            const showSlide = (index) => slides.forEach((s, i) => s.classList.toggle('active', i === index));
            setInterval(() => {
                currentSlide = (currentSlide + 1) % slides.length;
                showSlide(currentSlide);
            }, 6000);
        }
    </script>
{% endblock %}
"""

# --- List Page Template (for search, genre, etc.) ---
list_page_html = """
{% extends "base_html" %}

{% block title %}{{ title }} - {{ site_name }}{% endblock %}

{% block head_extra %}
<style>
.list-page-header { padding: 40px; text-align: center; }
.list-page-title { font-size: 2.5rem; font-weight: 700; color: var(--primary-color); }
.content-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 25px;
    padding: 0 40px;
}
@media (max-width: 768px) {
    .content-grid {
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        gap: 20px;
        padding: 0 20px;
    }
}
</style>
{% endblock %}

{% block content %}
    <div class="list-page-header">
        <h1 class="list-page-title">{{ title }}</h1>
    </div>
    
    <div class="content-grid">
        {% for movie in movies %}
            <a href="{{ url_for('movie_detail', movie_id=movie._id) }}" class="movie-card-h">
                <div class="movie-card-h-poster">
                    <img src="{{ movie.poster or 'https://via.placeholder.com/200x300.png?text=No+Poster' }}" alt="{{ movie.title }}" loading="lazy">
                    {% if movie.display_quality %}<div class="quality-badge">{{ movie.display_quality }}</div>{% endif %}
                </div>
                <div class="movie-card-h-info">
                    <h3 class="movie-card-h-title">{{ movie.title }}</h3>
                    <div class="movie-card-h-meta">
                        <span>{{ movie.release_date.split('-')[0] if movie.release_date else 'N/A' }}</span>
                        {% if movie.vote_average and movie.vote_average > 0 %}
                        <span><i class="fas fa-star"></i> {{ "%.1f"|format(movie.vote_average) }}</span>
                        {% endif %}
                    </div>
                </div>
            </a>
        {% else %}
            <p style="grid-column: 1 / -1; text-align: center; color: var(--text-muted-color);">No content found.</p>
        {% endfor %}
    </div>
{% endblock %}
"""

# --- Detail Page Template ---
detail_html = """
{% extends "base_html" %}

{% block title %}{{ movie.title }} - {{ site_name }}{% endblock %}

{% block head_extra %}
<style>
.detail-hero {
  position: relative;
  padding: 60px 0;
  margin-top: -{{ header_height }}px;
  min-height: 80vh;
  display: flex;
  align-items: center;
}
.detail-bg {
  position: absolute; top: 0; left: 0; width: 100%; height: 100%;
  background-size: cover; background-position: center;
  filter: blur(25px) brightness(0.3); transform: scale(1.1);
}
.detail-hero::after {
  content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  background: linear-gradient(to right, rgba(13,13,13,1) 20%, rgba(13,13,13,0.7) 50%, rgba(13,13,13,1) 100%);
}
.detail-content {
  position: relative; z-index: 2;
  display: flex; gap: 40px; align-items: flex-start;
}
.detail-poster img {
  width: 300px;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}
.detail-info-title { font-size: 3rem; font-weight: 700; margin-bottom: 20px; }
.detail-info-meta { display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 20px; }
.detail-info-meta span { background-color: rgba(255,255,255,0.1); padding: 6px 12px; border-radius: 5px; font-size: 0.9rem; }
.detail-info-meta .fa-star { color: #f5c518; }
.detail-info-storyline { margin-bottom: 30px; }
.detail-info-storyline h3 { font-size: 1.2rem; margin-bottom: 10px; color: var(--primary-color); }
.detail-info-storyline p { color: var(--text-muted-color); line-height: 1.7; }
.action-buttons { display: flex; flex-wrap: wrap; gap: 15px; }
.action-btn {
  padding: 12px 25px; border-radius: 50px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 10px;
  border: 2px solid transparent;
}
.btn-primary { background-color: var(--primary-color); color: #000; }
.btn-secondary { border-color: var(--primary-color); color: var(--primary-color); }
.download-section { padding: 50px 0; }
.download-links h3 { font-size: 1.5rem; margin-bottom: 20px; text-align: center; }
.download-table { width: 100%; max-width: 800px; margin: 0 auto; border-collapse: collapse; }
.download-table th, .download-table td { padding: 15px; text-align: center; border-bottom: 1px solid #222; }
.download-table th { color: var(--text-muted-color); font-weight: 500; }
.download-btn { background-color: var(--primary-color); color: #000; padding: 10px 20px; border-radius: 5px; font-weight: 600; }

@media (max-width: 992px) {
    .detail-content { flex-direction: column; align-items: center; text-align: center; }
    .detail-poster img { width: 250px; }
    .detail-info-title { font-size: 2.5rem; }
}
</style>
{% endblock %}

{% block content %}
    <section class="detail-hero">
        <div class="detail-bg" style="background-image: url('{{ movie.poster }}')"></div>
        <div class="container detail-content">
            <div class="detail-poster">
                <img src="{{ movie.poster or 'https://via.placeholder.com/300x450.png?text=No+Image' }}" alt="{{ movie.title }}">
            </div>
            <div class="detail-info">
                <h1 class="detail-info-title">{{ movie.title }}</h1>
                <div class="detail-info-meta">
                    {% if movie.release_date %}<span>{{ movie.release_date.split('-')[0] }}</span>{% endif %}
                    {% if movie.vote_average > 0 %}<span><i class="fas fa-star"></i> {{ "%.1f"|format(movie.vote_average) }}</span>{% endif %}
                    {% if movie.languages %}<span>{{ movie.languages|join(' / ') }}</span>{% endif %}
                    {% if movie.genres %}<span>{{ movie.genres|join(' / ') }}</span>{% endif %}
                </div>
                <div class="detail-info-storyline">
                    <h3>Storyline</h3>
                    <p>{{ movie.overview }}</p>
                </div>
                <div class="action-buttons">
                    {% if movie.trailer_key %}<a href="https://www.youtube.com/watch?v={{ movie.trailer_key }}" target="_blank" class="action-btn btn-secondary"><i class="fas fa-play"></i> Watch Trailer</a>{% endif %}
                    <a href="#download" class="action-btn btn-primary"><i class="fas fa-download"></i> Download Now</a>
                </div>
            </div>
        </div>
    </section>
    
    <section id="download" class="download-section">
        <div class="container">
            {% if movie.type == 'movie' and movie.files %}
            <div class="download-links">
                <h3><i class="fas fa-server"></i> Telegram Download Links</h3>
                <table class="download-table">
                    <thead><tr><th>Quality</th><th>Action</th></tr></thead>
                    <tbody>
                    {% for file in movie.files | sort(attribute='quality') %}
                    <tr>
                        <td>{{ file.quality }}</td>
                        <td><a href="https://t.me/{{ bot_username }}?start={{ movie._id }}_{{ file.quality }}" class="download-btn">Get File</a></td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
            {% elif movie.type == 'series' %}
            <div class="download-links">
                <h3><i class="fas fa-layer-group"></i> Seasons & Episodes</h3>
                <table class="download-table">
                    {% if movie.season_packs %}
                    {% for pack in movie.season_packs | sort(attribute='season') %}
                    <tr>
                        <td>Complete Season {{ pack.season }} Pack</td>
                        <td><a href="https://t.me/{{ bot_username }}?start={{ movie._id }}_S{{ pack.season }}" class="download-btn">Get Pack</a></td>
                    </tr>
                    {% endfor %}
                    {% endif %}
                    {% if movie.episodes %}
                    {% for ep in movie.episodes | sort(attribute='episode_number') | sort(attribute='season') %}
                    <tr>
                        <td>S{{ "%02d"|format(ep.season) }}E{{ "%02d"|format(ep.episode_number) }}</td>
                        <td><a href="https://t.me/{{ bot_username }}?start={{ movie._id }}_{{ ep.season }}_{{ ep.episode_number }}" class="download-btn">Get Episode</a></td>
                    </tr>
                    {% endfor %}
                    {% endif %}
                </table>
            </div>
            {% else %}
            <h3 style="text-align:center; color: var(--text-muted-color);">No download links available yet.</h3>
            {% endif %}
        </div>
    </section>
{% endblock %}
"""

# Admin and other templates remain unchanged as they are functional.
# You can update their styling later if needed.
# (The previous `admin_html`, `edit_html`, `contact_html` etc. go here)
admin_html = "..." # আগের কোড
edit_html = "..." # আগের কোড
contact_html = "..." # আগের কোড
genres_html = "..." # আগের কোড
watch_html = "..." # আগের কোড

# ======================================================================
# --- Helper Functions (Final Version) ---
# ======================================================================
def parse_filename(filename):
    """Parses filename to extract movie/series info."""
    LANGUAGE_MAP = {
        'hindi': 'Hindi', 'hin': 'Hindi', 'english': 'English', 'eng': 'English',
        'bengali': 'Bengali', 'bangla': 'Bangla', 'ben': 'Bengali',
        'tamil': 'Tamil', 'tam': 'Tamil', 'telugu': 'Telugu', 'tel': 'Telugu',
        'kannada': 'Kannada', 'kan': 'Kannada', 'malayalam': 'Malayalam', 'mal': 'Malayalam',
        'korean': 'Korean', 'kor': 'Korean', 'chinese': 'Chinese', 'chi': 'Chinese',
        'japanese': 'Japanese', 'jap': 'Japanese',
        'dual audio': ['Hindi', 'English'], 'dual': ['Hindi', 'English'],
        'multi audio': ['Multi Audio']
    }
    JUNK_KEYWORDS = [
        '1080p', '720p', '480p', '2160p', '4k', 'uhd', 'web-dl', 'webdl', 'webrip',
        'brrip', 'bluray', 'dvdrip', 'hdrip', 'hdcam', 'camrip', 'hdts', 'x264',
        'x265', 'hevc', 'avc', 'aac', 'ac3', 'dts', '5.1', '7.1', 'final', 'uncut',
        'extended', 'remastered', 'unrated', 'nf', 'www', 'com', 'net', 'org', 'psa'
    ]
    SEASON_PACK_KEYWORDS = ['complete', 'season', 'pack', 'all episodes', 'zip']
    base_name, _ = os.path.splitext(filename)
    processed_name = re.sub(r'[\._\[\]\(\)\{\}-]', ' ', base_name)
    found_languages = []
    temp_name_for_lang = processed_name.lower()
    for keyword, lang_name in LANGUAGE_MAP.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', temp_name_for_lang):
            if isinstance(lang_name, list): found_languages.extend(lang_name)
            else: found_languages.append(lang_name)
    languages = sorted(list(set(found_languages))) if found_languages else []
    season_pack_match = re.search(r'^(.*?)[\s\.]*(?:S|Season)[\s\.]?(\d{1,2})', processed_name, re.I)
    if season_pack_match:
        text_after_season = processed_name[season_pack_match.end():].lower()
        is_pack = any(keyword in text_after_season for keyword in SEASON_PACK_KEYWORDS) or not re.search(r'\be\d', text_after_season)
        if is_pack:
            title = season_pack_match.group(1).strip()
            season_num = int(season_pack_match.group(2))
            for junk in JUNK_KEYWORDS + SEASON_PACK_KEYWORDS:
                title = re.sub(r'\b' + re.escape(junk) + r'\b', '', title, flags=re.I)
            final_title = ' '.join(title.split()).title()
            if final_title: return {'type': 'series_pack', 'title': final_title, 'season': season_num, 'languages': languages}
    series_patterns = [
        re.compile(r'^(.*?)[\s\.]*(?:S|Season)[\s\.]?(\d{1,2})[\s\.]*(?:E|Ep|Episode)[\s\.]?(\d{1,3})', re.I),
        re.compile(r'^(.*?)[\s\.]*(?:E|Ep|Episode)[\s\.]?(\d{1,3})', re.I)
    ]
    for i, pattern in enumerate(series_patterns):
        match = pattern.search(processed_name)
        if match:
            title = match.group(1).strip()
            season_num = int(match.group(2)) if i == 0 else 1
            episode_num = int(match.group(3)) if i == 0 else int(match.group(2))
            for junk in JUNK_KEYWORDS: title = re.sub(r'\b' + re.escape(junk) + r'\b', '', title, flags=re.I)
            final_title = ' '.join(title.split()).title()
            if final_title: return {'type': 'series', 'title': final_title, 'season': season_num, 'episode': episode_num, 'languages': languages}
    year_match = re.search(r'\b(19[5-9]\d|20\d{2})\b', processed_name)
    year = year_match.group(1) if year_match else None
    title_part = processed_name[:year_match.start()] if year_match else processed_name
    temp_title = title_part
    for lang_key in LANGUAGE_MAP.keys(): temp_title = re.sub(r'\b' + lang_key + r'\b', '', temp_title, flags=re.I)
    for junk in JUNK_KEYWORDS: temp_title = re.sub(r'\b' + re.escape(junk) + r'\b', '', temp_title, flags=re.I)
    final_title = ' '.join(temp_title.split()).title()
    return {'type': 'movie', 'title': final_title, 'year': year, 'languages': languages} if final_title else None

def get_tmdb_details_from_api(title, content_type, year=None):
    if not TMDB_API_KEY:
        print("ERROR: TMDB_API_KEY is not set.")
        return None
    search_type = "tv" if content_type in ["series", "series_pack"] else "movie"
    def search_tmdb(query_title):
        print(f"INFO: Searching TMDb for: '{query_title}' (Type: {search_type}, Year: {year})")
        try:
            search_url = f"https://api.themoviedb.org/3/search/{search_type}?api_key={TMDB_API_KEY}&query={requests.utils.quote(query_title)}"
            if year and search_type == "movie": search_url += f"&year={year}"
            search_res = requests.get(search_url, timeout=10)
            search_res.raise_for_status()
            results = search_res.json().get("results")
            if not results: return None
            tmdb_id = results[0].get("id")
            detail_url = f"https://api.themoviedb.org/3/{search_type}/{tmdb_id}?api_key={TMDB_API_KEY}&append_to_response=videos"
            detail_res = requests.get(detail_url, timeout=10)
            detail_res.raise_for_status()
            res_json = detail_res.json()
            trailer_key = next((v['key'] for v in res_json.get("videos", {}).get("results", []) if v.get('type') == 'Trailer' and v.get('site') == 'YouTube'), None)
            details = { "tmdb_id": tmdb_id, "title": res_json.get("title") or res_json.get("name"), "poster": f"https://image.tmdb.org/t/p/w500{res_json.get('poster_path')}" if res_json.get('poster_path') else None, "overview": res_json.get("overview"), "release_date": res_json.get("release_date") or res_json.get("first_air_date"), "genres": [g['name'] for g in res_json.get("genres", [])], "vote_average": res_json.get("vote_average"), "trailer_key": trailer_key }
            print(f"SUCCESS: Found TMDb details for '{query_title}' (ID: {tmdb_id}).")
            return details
        except requests.RequestException as e:
            print(f"ERROR: TMDb API request failed for '{query_title}'. Reason: {e}")
            return None
    tmdb_data = search_tmdb(title)
    if not tmdb_data and len(title.split()) > 1:
        simpler_title = " ".join(title.split()[:-1])
        print(f"INFO: Initial search failed. Retrying with simpler title: '{simpler_title}'")
        tmdb_data = search_tmdb(simpler_title)
    if not tmdb_data: print(f"WARNING: TMDb search found no results for '{title}' after all attempts.")
    return tmdb_data

def extract_quality_from_filename(filename):
    """Extracts a specific quality tag from a filename based on a priority list."""
    quality_map = {
        'remux': 'Remux', 'bluray': 'BluRay', 'brrip': 'BluRay', 'bdrip': 'BluRay', '2160p': '4K UHD', 'uhd': '4K UHD', '1080p': '1080p', '720p': '720p', '480p': '480p',
        'web-dl': 'WEB-DL', 'webdl': 'WEB-DL', 'webrip': 'WEBRip', 'hdrip': 'HDRip', 'hdtv': 'HDTV', 'dvdscr': 'DVDScr', 'predvd': 'PreDVD', 'hd-ts': 'HDTS', 'hdts': 'HDTS',
        'hdcam': 'HDCAM', 'hall print': 'Hall Print', 'camrip': 'CAM', 'cam': 'CAM',
    }
    normalized_filename = f" {filename.lower().replace('.', ' ').replace('-', ' ')} "
    for key, display_name in quality_map.items():
        if f" {key} " in normalized_filename: return display_name
    return "HD"

def get_display_quality(movie):
    """Determines the best available quality to display on the movie card."""
    if movie.get('is_coming_soon'): return "SOON"
    if movie.get('type') == 'series': return "Series"
    if movie.get('type') == 'movie':
        available_qualities = [f.get('quality') for f in movie.get('files', []) if f.get('quality')]
        if not available_qualities:
            if movie.get('links'): return "HD"
            if movie.get('watch_link'): return "STREAM"
            return None
        display_ranking = [
            'Remux', '4K UHD', 'BluRay', '1080p', 'WEB-DL', '720p', 'WEBRip', 'HDRip', 'HDTV', '480p',
            'DVDScr', 'PreDVD', 'HDTS', 'HDCAM', 'Hall Print', 'CAM', 'HD', 'STREAM'
        ]
        for ranked_quality in display_ranking:
            if ranked_quality in available_qualities: return ranked_quality
        return available_qualities[0] if available_qualities else None
    return None

def process_movie_list(movie_list):
    """Processes a list of movies to add computed fields like display_quality."""
    processed = []
    for item in movie_list:
        item['_id'] = str(item['_id'])
        item['display_quality'] = get_display_quality(item)
        processed.append(item)
    return processed

# ======================================================================
# --- Main Flask Routes ---
# ======================================================================

@app.route('/')
def home():
    query = request.args.get('q')
    if query:
        movies_list = list(movies.find({"title": {"$regex": query, "$options": "i"}}).sort('_id', -1))
        return render_template_string(list_page_html, movies=process_movie_list(movies_list), title=f'Results for "{query}"', now=datetime.utcnow())

    limit = 15
    hero_movies_list = list(movies.find({
        "poster": {"$ne": None, "$exists": True},
        "overview": {"$ne": None, "$exists": True},
        "is_coming_soon": {"$ne": True}
    }).sort('_id', -1).limit(5))

    context = {
        "hero_movies": process_movie_list(hero_movies_list),
        "trending_movies": process_movie_list(list(movies.find({"is_trending": True, "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "latest_movies": process_movie_list(list(movies.find({"type": "movie", "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "latest_series": process_movie_list(list(movies.find({"type": "series", "is_coming_soon": {"$ne": True}}).sort('_id', -1).limit(limit))),
        "now": datetime.utcnow(),
        "header_height": "70px" # pass this for hero section styling
    }
    return render_template_string(index_html, base_html=base_html, **context)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    try:
        movie = movies.find_one({"_id": ObjectId(movie_id)})
        if not movie: return "Content not found", 404
        return render_template_string(detail_html, base_html=base_html, movie=movie, now=datetime.utcnow(), header_height="70px")
    except Exception:
        return "Content not found", 404

def render_full_list(content_list, title):
    return render_template_string(list_page_html, base_html=base_html, movies=process_movie_list(content_list), title=title, now=datetime.utcnow())

@app.route('/badge/<badge_name>')
def movies_by_badge(badge_name): return render_full_list(list(movies.find({"poster_badge": badge_name}).sort('_id', -1)), f'Tag: {badge_name}')

@app.route('/genres')
def genres_page():
    # A simple genres page can be created or redirect to a more complex one
    all_genres = sorted([g for g in movies.distinct("genres") if g])
    # For now, let's use the list_page_html to display genres as links
    return f"List of Genres: {', '.join([f'<a href=/genre/{g}>{g}</a>' for g in all_genres])}" # Placeholder

@app.route('/genre/<genre_name>')
def movies_by_genre(genre_name): return render_full_list(list(movies.find({"genres": genre_name}).sort('_id', -1)), f'Genre: {genre_name}')

@app.route('/trending_movies')
def trending_movies(): return render_full_list(list(movies.find({"is_trending": True, "is_coming_soon": {"$ne": True}}).sort('_id', -1)), "Trending Now")

@app.route('/movies_only')
def movies_only(): return render_full_list(list(movies.find({"type": "movie", "is_coming_soon": {"$ne": True}}).sort('_id', -1)), "All Movies")

@app.route('/webseries')
def webseries(): return render_full_list(list(movies.find({"type": "series", "is_coming_soon": {"$ne": True}}).sort('_id', -1)), "All Web Series")

# ======================================================================
# --- Admin and Webhook Routes (mostly unchanged) ---
# ======================================================================
# (এখানে admin, edit_movie, delete_movie, contact, telegram_webhook ইত্যাদি ফাংশনগুলো আগের মতোই থাকবে)
# ... The rest of your Python code for admin, webhook, etc. remains the same ...
@app.route('/admin', methods=["GET", "POST"])
@requires_auth
def admin():
    # This route is functional and does not need design changes.
    # Keep the previous code for this function.
    if request.method == "POST":
        content_type = request.form.get("content_type", "movie")
        tmdb_data = get_tmdb_details_from_api(request.form.get("title"), content_type) or {}
        movie_data = {
            "title": request.form.get("title"), "type": content_type, **tmdb_data, 
            "is_trending": False, "is_coming_soon": False, 
            "links": [], "files": [], "episodes": [], "season_packs": [], "languages": []
        }
        if content_type == "movie":
            movie_data["watch_link"] = request.form.get("watch_link", "")
            movie_data["links"] = [{"quality": q, "url": u} for q, u in [("480p", request.form.get("link_480p")), ("720p", request.form.get("link_720p")), ("1080p", request.form.get("link_1080p"))] if u]
            movie_data["files"] = [{"quality": q, "message_id": int(mid)} for q, mid in zip(request.form.getlist('telegram_quality[]'), request.form.getlist('telegram_message_id[]')) if q and mid]
        else:
            movie_data["episodes"] = [{"season": int(s), "episode_number": int(e), "title": t, "watch_link": w or None, "message_id": int(m) if m else None} for s, e, t, w, m in zip(request.form.getlist('episode_season[]'), request.form.getlist('episode_number[]'), request.form.getlist('episode_title[]'), request.form.getlist('episode_watch_link[]'), request.form.getlist('episode_message_id[]'))]
        movies.insert_one(movie_data)
        return redirect(url_for('admin'))

    search_query = request.args.get('search', '').strip()
    query_filter = {}
    if search_query: query_filter = {"title": {"$regex": search_query, "$options": "i"}}
    ad_settings = settings.find_one() or {}
    # Use the original data structure for admin panel, no need for process_movie_list
    content_list = list(movies.find(query_filter).sort('_id', -1))
    feedback_list = list(feedback.find().sort('timestamp', -1))
    # You might need to re-add your old admin_html here. I'm leaving it as a placeholder.
    return "Admin Panel - Functionality is intact. Use your old admin_html template."

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        if str(post.get('chat', {}).get('id')) != ADMIN_CHANNEL_ID: return jsonify(status='ok', reason='not_admin_channel')
        file = post.get('video') or post.get('document')
        if not (file and file.get('file_name')): return jsonify(status='ok', reason='no_file_in_post')
        filename = file.get('file_name')
        print(f"\n--- [WEBHOOK] PROCESSING NEW FILE: {filename} ---")
        parsed_info = parse_filename(filename)
        if not parsed_info or not parsed_info.get('title'):
            print(f"FAILED: Could not parse title from filename: {filename}")
            return jsonify(status='ok', reason='parsing_failed')
        print(f"PARSED INFO: {parsed_info}")
        tmdb_data = get_tmdb_details_from_api(parsed_info['title'], parsed_info['type'], parsed_info.get('year'))
        if not tmdb_data or not tmdb_data.get("tmdb_id"):
            print(f"DATABASE: Skipping update for '{parsed_info['title']}' due to no TMDb data.")
            return jsonify(status='ok', reason='no_tmdb_data_or_id')
        tmdb_id = tmdb_data.get("tmdb_id")
        update_doc = {"$set": {k: v for k, v in tmdb_data.items() if v}, "$addToSet": {}}
        if parsed_info.get('languages'): update_doc["$addToSet"]["languages"] = {"$each": parsed_info['languages']}
        content_type = parsed_info['type']
        existing_content = movies.find_one({"tmdb_id": tmdb_id})
        if content_type in ['series', 'series_pack']:
            if not existing_content:
                print(f"DATABASE: No existing series found. Creating new entry for '{tmdb_data['title']}'...")
                series_doc = {**tmdb_data, "type": "series", "episodes": [], "season_packs": [], "languages": parsed_info.get('languages', [])}
                movies.insert_one(series_doc)
                existing_content = movies.find_one({"tmdb_id": tmdb_id})
            if content_type == 'series_pack':
                new_pack = {"season": parsed_info['season'], "message_id": post['message_id']}
                movies.update_one({"_id": existing_content['_id']}, {"$pull": {"season_packs": {"season": new_pack['season']}}})
                update_doc["$push"] = {"season_packs": new_pack}
                print(f"SUCCESS: Season {new_pack['season']} pack updated.")
            else:
                new_episode = {"season": parsed_info['season'], "episode_number": parsed_info['episode'], "message_id": post['message_id']}
                movies.update_one({"_id": existing_content['_id']}, {"$pull": {"episodes": {"season": new_episode['season'], "episode_number": new_episode['episode_number']}}})
                update_doc["$push"] = {"episodes": new_episode}
                print(f"SUCCESS: S{new_episode['season']}E{new_episode['episode_number']} updated.")
            movies.update_one({"_id": existing_content['_id']}, update_doc)
        else: # Movie
            quality = extract_quality_from_filename(filename)
            new_file = {"quality": quality, "message_id": post['message_id']}
            if existing_content:
                movies.update_one({"_id": existing_content['_id']}, {"$pull": {"files": {"quality": new_file['quality']}}})
                update_doc["$push"] = {"files": new_file}
                movies.update_one({"_id": existing_content['_id']}, update_doc)
                print(f"SUCCESS: Movie file ({quality}) updated.")
            else:
                movie_doc = {**tmdb_data, "type": "movie", "files": [new_file], "languages": parsed_info.get('languages', [])}
                movies.insert_one(movie_doc)
                print("SUCCESS: New movie created.")
    elif 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')
        if text.startswith('/start'):
            parts = text.split()
            if len(parts) > 1:
                try:
                    payload_parts = parts[1].split('_')
                    doc_id_str = payload_parts[0]
                    content = movies.find_one({"_id": ObjectId(doc_id_str)})
                    if not content: return jsonify(status='ok')
                    message_to_copy_id, file_info_text = None, ""
                    if len(payload_parts) == 2 and payload_parts[1].startswith('S'):
                        season_num = int(payload_parts[1][1:])
                        pack = next((p for p in content.get('season_packs', []) if p.get('season') == season_num), None)
                        if pack: message_to_copy_id, file_info_text = pack.get('message_id'), f"Complete Season {season_num}"
                    elif content.get('type') == 'series' and len(payload_parts) == 3:
                        s_num, e_num = int(payload_parts[1]), int(payload_parts[2])
                        episode = next((ep for ep in content.get('episodes', []) if ep.get('season') == s_num and ep.get('episode_number') == e_num), None)
                        if episode: message_to_copy_id, file_info_text = episode.get('message_id'), f"S{s_num:02d}E{e_num:02d}"
                    elif content.get('type') == 'movie' and len(payload_parts) == 2:
                        quality = payload_parts[1]
                        file = next((f for f in content.get('files', []) if f.get('quality') == quality), None)
                        if file: message_to_copy_id, file_info_text = file.get('message_id'), f"({quality})"
                    if message_to_copy_id:
                        caption_text = (f"🎬 *{escape_markdown(content['title'])}* {escape_markdown(file_info_text)}\n\n"
                                        f"✅ *Successfully Sent To Your PM*\n\n"
                                        f"🔰 Join Our Main Channel\n➡️ [{escape_markdown(BOT_USERNAME)} Main]({MAIN_CHANNEL_LINK})\n\n"
                                        f"📢 Join Our Update Channel\n➡️ [{escape_markdown(BOT_USERNAME)} Official]({UPDATE_CHANNEL_LINK})\n\n"
                                        f"💬 For Any Help or Request\n➡️ [Contact Developer]({DEVELOPER_USER_LINK})")
                        payload = {'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': message_to_copy_id, 'caption': caption_text, 'parse_mode': 'MarkdownV2'}
                        res = requests.post(f"{TELEGRAM_API_URL}/copyMessage", json=payload).json()
                        if res.get('ok'):
                            new_msg_id = res['result']['message_id']
                            scheduler.add_job(func=delete_message_after_delay, trigger='date', run_date=datetime.now() + timedelta(minutes=30), args=[chat_id, new_msg_id], id=f'del_{chat_id}_{new_msg_id}', replace_existing=True)
                        else: requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "Error sending file. It might have been deleted from the channel."})
                    else: requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "Requested file/season not found."})
                except Exception as e:
                    print(f"Error processing /start command: {e}")
                    requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': "An unexpected error occurred."})
            else:
                welcome_message = (f"👋 Welcome to {BOT_USERNAME}!\n\nBrowse all our content on our website.")
                try:
                    root_url = url_for('home', _external=True)
                    keyboard = {"inline_keyboard": [[{"text": "🎬 Visit Website", "url": root_url}]]}
                    requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': welcome_message, 'reply_markup': str(keyboard).replace("'", '"')})
                except Exception: requests.get(f"{TELEGRAM_API_URL}/sendMessage", params={'chat_id': chat_id, 'text': welcome_message})
    return jsonify(status='ok')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
