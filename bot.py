import os
import re
import requests
from flask import Flask, request, jsonify, abort
from pymongo import MongoClient
from bson.objectid import ObjectId
from jinja2 import Environment, BaseLoader, TemplateNotFound

# ======================================================================
# --- আপনার ব্যক্তিগত তথ্য সরাসরি এখানে বসানো হয়েছে ---
# ======================================================================
MONGO_URI = "mongodb+srv://mesohas358:mesohas358@cluster0.6kxy1vc.mongodb.net/movie_database?retryWrites=true&w=majority&appName=Cluster0"
BOT_TOKEN = "7931162174:AAGK8aSdqoYpZ4bsSXp36dp6zbVnYeenowA"
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"
ADMIN_CHANNEL_ID = "-1002853936940"
# ======================================================================

# --- অ্যাপ এবং ডাটাবেস সংযোগ ---
app = Flask(__name__)
try:
    client = MongoClient(MONGO_URI)
    db = client.get_database() 
    movies_collection = db.movies
    client.admin.command('ping')
    print("SUCCESS: MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")
    movies_collection = None

# --- HTML এবং CSS টেমপ্লেটগুলো ---
TEMPLATES = {
    "base": """
<!doctype html>
<html lang="bn">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}অটো বাংলা মুভি{% endblock %}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"/>
    <style>{{ css_code|safe }}</style>
</head>
<body>
    <header class="sticky-top">
        <nav class="navbar navbar-expand-lg main-nav">
            <div class="container"> <a class="navbar-brand" href="/"><i class="fa-solid fa-film"></i> অটো বাংলা মুভি</a> </div>
        </nav>
    </header>
    <main class="container my-5"> {% block content %}{% endblock %} </main>
    <footer class="text-center py-4 mt-auto"> <p class="text-white-50">© 2024 All Rights Reserved.</p> </footer>
</body>
</html>
""",
    "index": """
{% extends "base" %}
{% block title %}সকল মুভি{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4"> <h2 class="section-title">সর্বশেষ আপলোড</h2> </div>
<div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-6 g-4">
    {% for movie in movies %}
    <div class="col">
        <a href="/movie/{{ movie._id }}" class="text-decoration-none">
            <div class="movie-card">
                <img src="{{ movie.poster_url or 'https://via.placeholder.com/500x750.png?text=No+Image' }}" class="movie-poster" alt="{{ movie.title }}" loading="lazy">
                <div class="movie-overlay">
                    <div class="movie-info">
                        <h5 class="movie-title">{{ movie.title }}</h5>
                        <div class="d-flex justify-content-between align-items-center mt-2">
                            <span class="badge bg-warning text-dark"><i class="fa-solid fa-star me-1"></i>{{ movie.rating }}</span>
                            <span class="badge bg-light text-dark">{{ movie.release_year }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </a>
    </div>
    {% else %}
    <div class="col-12 text-center py-5"> <h4 class="text-white-50">এখনও কোনো মুভি আপলোড করা হয়নি।</h4> <p class="text-white-50">আপনার টেলিগ্রাম চ্যানেলে ফাইল আপলোড করুন।</p> </div>
    {% endfor %}
</div>
{% endblock %}
""",
    "detail": """
{% extends "base" %}
{% block title %}{{ movie.title }}{% endblock %}
{% block content %}
<div class="card movie-detail-card bg-transparent border-0">
    <div class="row g-0">
        <div class="col-md-4 text-center">
            <img src="{{ movie.poster_url or 'https://via.placeholder.com/500x750.png?text=No+Image' }}" class="img-fluid rounded-3 movie-detail-poster" alt="{{ movie.title }}">
        </div>
        <div class="col-md-8">
            <div class="card-body p-lg-5 p-md-4 p-2">
                <h1 class="card-title display-5">{{ movie.title }}</h1>
                <div class="d-flex align-items-center gap-3 my-3">
                    <span class="badge fs-6 text-bg-warning"><i class="fa-solid fa-star me-1"></i> IMDb: {{ movie.rating }}/10</span>
                    <span class="badge fs-6 text-bg-secondary">{{ movie.release_year }}</span>
                </div>
                <h5 class="mt-4 mb-3">কাহিনী সংক্ষেপ</h5>
                <p class="card-text text-white-50">{{ movie.description or 'No description available.' }}</p>
                <div class="mt-5">
                    <h5 class="mb-3">ডাউনলোড লিঙ্ক</h5>
                    <a href="{{ movie.download_url }}" class="btn btn-primary btn-lg" target="_blank">
                        <i class="fa-solid fa-download me-2"></i> ডাউনলোড করুন
                    </a>
                </div>
                <p class="text-muted small mt-3">এই লিঙ্কে ক্লিক করলে আপনাকে সরাসরি টেলিগ্রাম পোস্টে নিয়ে যাওয়া হবে।</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""
}

CSS_CODE = """
:root { --primary-color: #e50914; --background-color: #141414; --card-background: #1f1f1f; --text-color: #ffffff; --font-family: 'Hind Siliguri', sans-serif; }
body { background-color: var(--background-color) !important; color: var(--text-color) !important; font-family: var(--font-family); display: flex; flex-direction: column; min-height: 100vh; }
.main-nav { background-color: rgba(20, 20, 20, 0.85); backdrop-filter: blur(10px); border-bottom: 1px solid #222; }
.navbar-brand { font-weight: 700; color: var(--primary-color) !important; font-size: 1.5rem; }
.section-title { font-weight: 600; border-left: 4px solid var(--primary-color); padding-left: 15px; }
.movie-card { position: relative; overflow: hidden; border-radius: 8px; background-color: var(--card-background); transition: transform 0.3s ease, box-shadow 0.3s ease; cursor: pointer; border: 1px solid #2a2a2a; }
.movie-card:hover { transform: scale(1.05); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5); }
.movie-poster { width: 100%; height: auto; aspect-ratio: 2/3; object-fit: cover; display: block; }
.movie-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 50%); display: flex; align-items: flex-end; opacity: 0; transition: opacity 0.3s ease; }
.movie-card:hover .movie-overlay { opacity: 1; }
.movie-info { padding: 1rem; width: 100%; }
.movie-title { font-size: 1rem; font-weight: 600; color: var(--text-color); margin-bottom: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.movie-detail-poster { max-width: 350px; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.7); }
.movie-detail-card .display-5 { font-weight: 700; }
.btn-primary { background-color: var(--primary-color); border-color: var(--primary-color); }
.btn-primary:hover { background-color: #c40812; border-color: #c40812; }
"""

class DictLoader(BaseLoader):
    def __init__(self, templates): self.templates = templates
    def get_source(self, environment, template):
        if template in self.templates: return self.templates[template], None, lambda: True
        raise TemplateNotFound(template)

jinja_env = Environment(loader=DictLoader(TEMPLATES))
def render_template(template_name, **context):
    template = jinja_env.get_template(template_name)
    return template.render(css_code=CSS_CODE, **context)

# --- হেল্পার ফাংশন ---
def parse_movie_name(filename):
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name, re.IGNORECASE)
    if match: return match.group(1).strip(), match.group(2).strip()
    return None, None

def get_tmdb_info(title, year):
    params = {'api_key': TMDB_API_KEY, 'query': title, 'primary_release_year': year}
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params)
        r.raise_for_status()
        res = r.json()
        if res.get('results'):
            data = res['results'][0]
            poster = data.get('poster_path')
            return {
                'title': data.get('title'), 'description': data.get('overview'),
                'poster_url': f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                'release_year': data.get('release_date', '')[:4],
                'rating': round(data.get('vote_average', 0), 1)
            }
    except requests.exceptions.RequestException as e: print(f"Error: {e}")
    return None

# --- Flask রাউট ---
@app.route('/')
def index():
    if movies_collection is None: return "Database connection failed.", 500
    all_movies = list(movies_collection.find().sort('_id', -1))
    return render_template('index', movies=all_movies)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    if movies_collection is None: return "Database connection failed.", 500
    try:
        movie = movies_collection.find_one({'_id': ObjectId(movie_id)})
        if movie: return render_template('detail', movie=movie)
        else: abort(404)
    except: abort(404)

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    if movies_collection is None: return jsonify(status='failed', reason='db_error')
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        chat_id = str(post['chat']['id'])
        if chat_id == ADMIN_CHANNEL_ID and ('video' in post or 'document' in post):
            file = post.get('video') or post.get('document')
            title, year = parse_movie_name(file.get('file_name', ''))
            if title and year:
                info = get_tmdb_info(title, year)
                if info:
                    # === পরিবর্তন এখানে: সরাসরি পোস্টের লিঙ্ক তৈরি করা হচ্ছে ===
                    channel_username_or_id = chat_id.replace("-100", "") # পাবলিক চ্যানেলের জন্য username, প্রাইভেটের জন্য chat_id
                    message_id = post['message_id']
                    # নোট: যদি আপনার চ্যানেল প্রাইভেট হয়, এই লিঙ্ক কাজ নাও করতে পারে। সেক্ষেত্রে চ্যানেলটিকে পাবলিক করতে হবে।
                    # যদি চ্যানেল পাবলিক করতে না চান, তাহলে অন্য সমাধান লাগবে।
                    # আপাতত ধরে নিচ্ছি চ্যানেল পাবলিক করা সম্ভব। চ্যানেলের একটি ইউজারনেম সেট করুন।
                    # যেমন, @my_movie_channel. তাহলে নিচের লাইনে channel_username_or_id এর জায়গায় 'my_movie_channel' বসাতে হবে।
                    
                    # চ্যানেল প্রাইভেট হলে এই লিঙ্ক কাজ করবে না। একটি PUBLIC CHANNEL USERNAME দিন, যেমন 'your_channel_name'
                    # আমি আপাতত একটি placeholder দিচ্ছি, আপনাকে এটি পরিবর্তন করতে হতে পারে।
                    # আপনার চ্যানেলের একটি ইউজারনেম দিন (যেমন @my_movies), তারপর নিচের লাইনে 'c' এর বদলে সেই ইউজারনেম লিখুন।
                    info['download_url'] = f"https://t.me/c/{channel_username_or_id}/{message_id}"
                    
                    movies_collection.insert_one(info)
                    print(f"SUCCESS: Movie '{info['title']}' added. Link: {info['download_url']}")
    return jsonify(status='ok')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
