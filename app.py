======================================================================
FILE 1: app.py
======================================================================
# এই সম্পূর্ণ কোডটি কপি করে app.py নামে সেভ করুন।
# এটি আপনার প্রজেক্টের মূল ফোল্ডারে থাকবে।

import os
import re
import requests
from flask import Flask, request, jsonify, render_template, abort
from pymongo import MongoClient
from bson.objectid import ObjectId

# --- আপনার ব্যক্তিগত তথ্য সরাসরি এখানে বসানো হয়েছে ---
MONGO_URI = "mongodb+srv://mesohas358:mesohas358@cluster0.6kxy1vc.mongodb.net/movie_database?retryWrites=true&w=majority&appName=Cluster0"
BOT_TOKEN = "7931162174:AAGK8aSdqoYpZ4bsSXp36dp6zbVnYeenowA"
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"
ADMIN_CHANNEL_ID = "-1002853936940"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- অ্যাপ এবং ডাটাবেস সংযোগ ---
app = Flask(__name__)
try:
    print("Trying to connect to MongoDB...")
    client = MongoClient(MONGO_URI)
    db = client.get_database() 
    movies_collection = db.movies
    client.admin.command('ping') # সংযোগ পরীক্ষা করার জন্য
    print("SUCCESS: MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")
    movies_collection = None

# --- হেল্পার ফাংশন ---
def parse_movie_name(filename):
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        year = match.group(2).strip()
        return title, year
    return None, None

def get_tmdb_info(title, year):
    search_url = "https://api.themoviedb.org/3/search/movie"
    params = {'api_key': TMDB_API_KEY, 'query': title, 'primary_release_year': year}
    try:
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('results'):
            movie_data = data['results'][0]
            poster_path = movie_data.get('poster_path')
            return {
                'title': movie_data.get('title'),
                'description': movie_data.get('overview'),
                'poster_url': f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
                'release_year': movie_data.get('release_date', '')[:4],
                'rating': round(movie_data.get('vote_average', 0), 1)
            }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching from TMDb: {e}")
    return None

def get_telegram_file_link(file_id):
    url = f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get('ok'):
            file_path = data['result']['file_path']
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    except requests.exceptions.RequestException as e:
        print(f"Error getting file link from Telegram: {e}")
    return None

# --- Flask রাউট ---
@app.route('/')
def index():
    if movies_collection is None: 
        return "Database connection failed. Please check your MongoDB URI and network access.", 500
    all_movies = list(movies_collection.find().sort('_id', -1))
    return render_template('index.html', movies=all_movies)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    if movies_collection is None: 
        return "Database connection failed.", 500
    try:
        movie = movies_collection.find_one({'_id': ObjectId(movie_id)})
        if movie: return render_template('movie_detail.html', movie=movie)
        else: abort(404)
    except Exception:
        abort(404)

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    print("Webhook received...")
    if movies_collection is None:
        print("Webhook skipped: Database not connected.")
        return jsonify(status='failed', reason='db_connection_error')
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        chat_id = str(post['chat']['id'])
        if chat_id == ADMIN_CHANNEL_ID and ('video' in post or 'document' in post):
            print("Post from admin channel received.")
            file_info = post.get('video') or post.get('document')
            if not file_info: return jsonify(status='ok')
            file_id = file_info['file_id']
            file_name = file_info.get('file_name', 'Untitled')
            title, year = parse_movie_name(file_name)
            if not title or not year:
                print(f"ERROR: Could not parse title/year from '{file_name}'")
                return jsonify(status='failed', reason='parsing_error')
            print(f"Parsed movie: {title} ({year})")
            movie_info = get_tmdb_info(title, year)
            if not movie_info:
                print(f"ERROR: TMDb info not found for '{title} ({year})'")
                return jsonify(status='failed', reason='tmdb_not_found')
            download_url = get_telegram_file_link(file_id)
            if not download_url:
                print(f"ERROR: Could not get download link for file_id '{file_id}'")
                return jsonify(status='failed', reason='telegram_link_error')
            movie_document = {
                'title': movie_info['title'], 'description': movie_info['description'],
                'poster_url': movie_info['poster_url'], 'release_year': movie_info['release_year'],
                'rating': movie_info['rating'], 'download_url': download_url
            }
            movies_collection.insert_one(movie_document)
            print(f"SUCCESS: Movie '{movie_info['title']}' added to database.")
    return jsonify(status='ok')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

======================================================================
FILE 2: requirements.txt
======================================================================
# এই লেখাটি কপি করে requirements.txt নামে সেভ করুন।
# এটিও আপনার প্রজেক্টের মূল ফোল্ডারে থাকবে।

Flask
requests
gunicorn
pymongo

======================================================================
FILE 3: templates/base.html
======================================================================
# প্রথমে templates নামে একটি ফোল্ডার তৈরি করুন।
# তারপর এই কোডটি কপি করে base.html নামে ওই ফোল্ডারের ভেতরে সেভ করুন।

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
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <header class="sticky-top">
        <nav class="navbar navbar-expand-lg main-nav">
            <div class="container">
                <a class="navbar-brand" href="{{ url_for('index') }}">
                    <i class="fa-solid fa-film"></i> অটো বাংলা মুভি
                </a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                    <span class="navbar-toggler-icon"></span>
                </button>
            </div>
        </nav>
    </header>
    <main class="container my-5">
        {% block content %}{% endblock %}
    </main>
    <footer class="text-center py-4 mt-auto">
        <p class="text-white-50">© {% now 'utc', '%Y' %} All Rights Reserved.</p>
    </footer>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>

======================================================================
FILE 4: templates/index.html
======================================================================
# এই কোডটি কপি করে index.html নামে templates ফোল্ডারের ভেতরে সেভ করুন।

{% extends 'base.html' %}
{% block title %}সকল মুভি{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h2 class="section-title">সর্বশেষ আপলোড</h2>
</div>
<div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-6 g-4">
    {% for movie in movies %}
    <div class="col">
        <a href="{{ url_for('movie_detail', movie_id=movie._id) }}" class="text-decoration-none">
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
    <div class="col-12 text-center py-5">
        <h4 class="text-white-50">এখনও কোনো মুভি আপলোড করা হয়নি।</h4>
        <p class="text-white-50">আপনার টেলিগ্রাম চ্যানেলে ফাইল আপলোড করুন।</p>
    </div>
    {% endfor %}
</div>
{% endblock %}

======================================================================
FILE 5: templates/movie_detail.html
======================================================================
# এই কোডটি কপি করে movie_detail.html নামে templates ফোল্ডারের ভেতরে সেভ করুন।

{% extends 'base.html' %}
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
                    <a href="{{ movie.download_url }}" class="btn btn-primary btn-lg me-2" target="_blank">
                        <i class="fa-solid fa-play me-2"></i> অনলাইনে দেখুন
                    </a>
                    <a href="{{ movie.download_url }}" class="btn btn-success btn-lg" target="_blank">
                        <i class="fa-solid fa-download me-2"></i> ডাউনলোড করুন
                    </a>
                </div>
                <p class="text-muted small mt-3">বিশেষ দ্রষ্টব্য: টেলিগ্রামের ডাউনলোড লিঙ্কগুলো সাময়িক এবং কিছু সময় পর কাজ নাও করতে পারে।</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}

======================================================================
FILE 6: static/css/style.css
======================================================================
# প্রথমে static নামে একটি ফোল্ডার, তার ভেতরে css নামে আরেকটি ফোল্ডার তৈরি করুন।
# তারপর এই কোডটি কপি করে style.css নামে ওই css ফোল্ডারের ভেতরে সেভ করুন।

:root {
    --primary-color: #e50914; /* Netflix Red */
    --background-color: #141414;
    --card-background: #1f1f1f;
    --text-color: #ffffff;
    --text-muted-color: #8c8c8c;
    --font-family: 'Hind Siliguri', sans-serif;
}
body {
    background-color: var(--background-color) !important;
    color: var(--text-color) !important;
    font-family: var(--font-family);
    display: flex;
    flex-direction: column;
    min-height: 100vh;
}
.main-nav {
    background-color: rgba(20, 20, 20, 0.85);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid #222;
}
.navbar-brand {
    font-weight: 700;
    color: var(--primary-color) !important;
    font-size: 1.5rem;
}
.section-title {
    font-weight: 600;
    border-left: 4px solid var(--primary-color);
    padding-left: 15px;
}
.movie-card {
    position: relative;
    overflow: hidden;
    border-radius: 8px;
    background-color: var(--card-background);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
    cursor: pointer;
    border: 1px solid #2a2a2a;
}
.movie-card:hover {
    transform: scale(1.05);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}
.movie-poster {
    width: 100%;
    height: auto;
    aspect-ratio: 2/3;
    object-fit: cover;
    display: block;
}
.movie-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 50%);
    display: flex;
    align-items: flex-end;
    opacity: 0;
    transition: opacity 0.3s ease;
}
.movie-card:hover .movie-overlay {
    opacity: 1;
}
.movie-info {
    padding: 1rem;
    width: 100%;
}
.movie-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-color);
    margin-bottom: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.movie-detail-poster {
    max-width: 350px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.7);
}
.movie-detail-card .display-5 {
    font-weight: 700;
}
.btn-primary {
    background-color: var(--primary-color);
    border-color: var(--primary-color);
}
.btn-primary:hover {
    background-color: #c40812;
    border-color: #c40812;
}

======================================================================
FILE 7: .gitignore
======================================================================
# এই লেখাটি কপি করে .gitignore নামে সেভ করুন।
# এটি আপনার প্রজেক্টের মূল ফোল্ডারে থাকবে।

__pycache__/
*.pyc
.idea/
.vscode/
