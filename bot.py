import os
import re
import requests
from flask import Flask, request, jsonify, abort, render_template_string, redirect, url_for, session, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
from jinja2 import Environment, BaseLoader, TemplateNotFound
from functools import wraps

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

# --- অ্যাপ এবং ডাটাবেস সংযোগ ---
app = Flask(__name__)
app.secret_key = os.urandom(24)

try:
    client = MongoClient(MONGO_URI)
    db = client.get_database() 
    content_collection = db.content
    client.admin.command('ping')
    print("SUCCESS: MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")
    content_collection = None

# --- HTML এবং CSS টেমপ্লেট (সম্পূর্ণ কোড এখানে) ---
TEMPLATES = {
    "base": """
<!doctype html>
<html lang="bn">
<head>
    <meta charset="utf-8"> <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}অটো মুভি ও সিরিজ{% endblock %}</title>
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
            <div class="container">
                <a class="navbar-brand" href="/"><i class="fa-solid fa-film"></i> অটো মুভি ও সিরিজ</a>
                {% if session.logged_in %}
                <a href="{{ url_for('admin_logout') }}" class="btn btn-sm btn-outline-light">Logout</a>
                {% endif %}
            </div>
        </nav>
    </header>
    <main class="container my-5"> {% block content %}{% endblock %} </main>
    <footer class="text-center py-4 mt-auto"> <p class="text-white-50">© 2024 All Rights Reserved.</p> </footer>
</body>
</html>
""",
    "index": """
{% extends "base" %}
{% block title %}সকল মুভি ও সিরিজ{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4"> <h2 class="section-title">সর্বশেষ আপলোড</h2> </div>
<div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-6 g-4">
    {% for content in contents %}
    <div class="col">
        <a href="/content/{{ content._id }}" class="text-decoration-none">
            <div class="movie-card">
                <img src="{{ content.poster_url or 'https://via.placeholder.com/500x750.png?text=No+Image' }}" class="movie-poster" alt="{{ content.title }}" loading="lazy">
                <div class="movie-overlay">
                    <div class="movie-info">
                        <h5 class="movie-title">{{ content.title }}</h5>
                        <div class="d-flex justify-content-between align-items-center mt-2">
                            <span class="badge bg-warning text-dark"><i class="fa-solid fa-star me-1"></i>{{ content.rating }}</span>
                            <span class="badge bg-light text-dark">{{ content.release_year }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </a>
    </div>
    {% else %}
    <div class="col-12 text-center py-5"> <h4 class="text-white-50">এখনও কোনো মুভি বা সিরিজ আপলোড করা হয়নি।</h4> </div>
    {% endfor %}
</div>
{% endblock %}
""",
    "detail": """
{% extends "base" %}
{% block title %}{{ content.title }}{% endblock %}
{% block content %}
<div class="card movie-detail-card bg-transparent border-0">
    <div class="row g-0">
        <div class="col-md-4 text-center">
            <img src="{{ content.poster_url or 'https://via.placeholder.com/500x750.png?text=No+Image' }}" class="img-fluid rounded-3 movie-detail-poster" alt="{{ content.title }}">
        </div>
        <div class="col-md-8">
            <div class="card-body p-lg-5 p-md-4 p-2">
                <h1 class="card-title display-5">{{ content.title }}</h1>
                <div class="d-flex align-items-center gap-3 my-3">
                    <span class="badge fs-6 text-bg-warning"><i class="fa-solid fa-star me-1"></i> IMDb: {{ content.rating }}/10</span>
                    <span class="badge fs-6 text-bg-secondary">{{ content.release_year }}</span>
                </div>
                <h5 class="mt-4 mb-3">কাহিনী সংক্ষেপ</h5>
                <p class="card-text text-white-50">{{ content.description or 'No description available.' }}</p>
                <div class="mt-5">
                    <h5 class="mb-3">পেতে নিচের বাটনে ক্লিক করুন</h5>
                    <a href="https://t.me/{{ bot_username }}?start=get_{{ content._id }}" class="btn btn-primary btn-lg" target="_blank">
                        <i class="fa-solid fa-robot me-2"></i> Get from Bot
                    </a>
                </div>
                <p class="text-muted small mt-3">এই লিঙ্কে ক্লিক করলে আপনাকে সরাসরি টেলিগ্রাম বটে নিয়ে যাওয়া হবে এবং ফাইলটি পাঠিয়ে দেওয়া হবে।</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",
    "admin_login": """
{% extends "base" %}
{% block title %}Admin Login{% endblock %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6 col-lg-4">
        <div class="card bg-dark border-secondary">
            <div class="card-body p-4">
                <h3 class="text-center mb-4">Admin Login</h3>
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    {% for category, message in messages %}
                      <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }}" role="alert">{{ message }}</div>
                    {% endfor %}
                  {% endif %}
                {% endwith %}
                <form method="post">
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <input type="text" class="form-control" id="username" name="username" required>
                    </div>
                    <div class="mb-3">
                        <label for="password" class="form-label">Password</label>
                        <input type="password" class="form-control" id="password" name="password" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Login</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
""",
    "admin_dashboard": """
{% extends "base" %}
{% block title %}Admin Dashboard{% endblock %}
{% block content %}
<h2 class="section-title mb-4">Admin Dashboard - All Content</h2>
<div class="table-responsive">
    <table class="table table-dark table-striped table-hover">
        <thead>
            <tr>
                <th>Poster</th>
                <th>Title</th>
                <th>Type</th>
                <th>Year</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for content in contents %}
            <tr>
                <td><img src="{{ content.poster_url or 'https://via.placeholder.com/50x75' }}" alt="poster" width="40"></td>
                <td>{{ content.title }}</td>
                <td><span class="badge text-bg-info">{{ content.type }}</span></td>
                <td>{{ content.release_year }}</td>
                <td>
                    <a href="{{ url_for('admin_edit', content_id=content._id) }}" class="btn btn-sm btn-warning">Edit</a>
                    <a href="{{ url_for('admin_delete', content_id=content._id) }}" class="btn btn-sm btn-danger" onclick="return confirm('Are you sure you want to delete this item?');">Delete</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
""",
    "admin_edit": """
{% extends "base" %}
{% block title %}Edit Content{% endblock %}
{% block content %}
<h2 class="section-title mb-4">Edit: {{ content.title }}</h2>
<form method="post">
    <div class="mb-3">
        <label for="title" class="form-label">Title</label>
        <input type="text" class="form-control" id="title" name="title" value="{{ content.title }}" required>
    </div>
    <div class="mb-3">
        <label for="description" class="form-label">Description</label>
        <textarea class="form-control" id="description" name="description" rows="5">{{ content.description }}</textarea>
    </div>
    <div class="mb-3">
        <label for="poster_url" class="form-label">Poster URL</label>
        <input type="url" class="form-control" id="poster_url" name="poster_url" value="{{ content.poster_url }}">
    </div>
    <button type="submit" class="btn btn-primary">Save Changes</button>
    <a href="{{ url_for('admin_dashboard') }}" class="btn btn-secondary">Cancel</a>
</form>
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
.table-dark { --bs-table-bg: #212529; --bs-table-striped-bg: #2c3034; --bs-table-hover-bg: #323539; }
"""

class DictLoader(BaseLoader):
    def __init__(self, templates): self.templates = templates
    def get_source(self, environment, template):
        if template in self.templates: return self.templates[template], None, lambda: True
        raise TemplateNotFound(template)

jinja_env = Environment(loader=DictLoader(TEMPLATES))
def render_template(template_name, **context):
    template = jinja_env.get_template(template_name)
    return render_template_string(template, css_code=CSS_CODE, bot_username=BOT_USERNAME, **context)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def parse_filename(filename):
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    series_match = re.search(r'^(.*?)[\s\._-]*[sS](\d+)[eE](\d+)', cleaned_name, re.IGNORECASE)
    if series_match: return {'type': 'tv', 'title': series_match.group(1).strip(), 'season': int(series_match.group(2)), 'episode': int(series_match.group(3))}
    movie_match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name, re.IGNORECASE)
    if movie_match: return {'type': 'movie', 'title': movie_match.group(1).strip(), 'year': movie_match.group(2).strip()}
    return None

def get_tmdb_info(parsed_info):
    api_url = f"https://api.themoviedb.org/3/search/{parsed_info['type']}"
    params = {'api_key': TMDB_API_KEY, 'query': parsed_info['title']}
    if parsed_info['type'] == 'movie': params['primary_release_year'] = parsed_info.get('year')
    try:
        r = requests.get(api_url, params=params)
        r.raise_for_status()
        res = r.json()
        if res.get('results'):
            data = res['results'][0]
            if parsed_info['type'] == 'movie':
                title, year = data.get('title'), data.get('release_date', '')[:4]
            else:
                title, year = f"{data.get('name')} S{parsed_info['season']:02d}E{parsed_info['episode']:02d}", data.get('first_air_date', '')[:4]
            poster = data.get('poster_path')
            return {'type': parsed_info['type'],'title': title,'description': data.get('overview'),'poster_url': f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,'release_year': year,'rating': round(data.get('vote_average', 0), 1)}
    except requests.exceptions.RequestException as e: print(f"Error fetching TMDb info: {e}")
    return None

# --- সাধারণ ব্যবহারকারীর রাউট ---
@app.route('/')
def index():
    if content_collection is None: return "Database connection failed.", 500
    all_content = list(content_collection.find().sort('_id', -1))
    return render_template('index', contents=all_content)

@app.route('/content/<content_id>')
def content_detail(content_id):
    if content_collection is None: return "Database connection failed.", 500
    try:
        content = content_collection.find_one({'_id': ObjectId(content_id)})
        if content: return render_template('detail', content=content)
        else: abort(404)
    except: abort(404)

# --- অ্যাডমিন প্যানেলের রাউট ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USER and request.form['password'] == ADMIN_PASS:
            session['logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')
    return render_template('admin_login')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    all_content = list(content_collection.find().sort('_id', -1))
    return render_template('admin_dashboard', contents=all_content)

@app.route('/admin/edit/<content_id>', methods=['GET', 'POST'])
@login_required
def admin_edit(content_id):
    if request.method == 'POST':
        updated_data = {
            'title': request.form['title'],
            'description': request.form['description'],
            'poster_url': request.form['poster_url']
        }
        content_collection.update_one({'_id': ObjectId(content_id)}, {'$set': updated_data})
        flash('Content updated successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    content = content_collection.find_one({'_id': ObjectId(content_id)})
    return render_template('admin_edit', content=content)

@app.route('/admin/delete/<content_id>')
@login_required
def admin_delete(content_id):
    content_collection.delete_one({'_id': ObjectId(content_id)})
    flash('Content deleted successfully!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('logged_in', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('admin_login'))

# --- টেলিগ্রাম ওয়েবহুক ---
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        if str(post['chat']['id']) == ADMIN_CHANNEL_ID:
            file = post.get('video') or post.get('document')
            if file and content_collection is not None:
                parsed_info = parse_filename(file.get('file_name', ''))
                if parsed_info:
                    tmdb_data = get_tmdb_info(parsed_info)
                    if tmdb_data:
                        tmdb_data['message_id_in_channel'] = post['message_id']
                        content_collection.insert_one(tmdb_data)
                        print(f"SUCCESS: Content '{tmdb_data['title']}' info saved.")
    elif 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')
        if text == '/start':
            requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Welcome! Please browse our website.")
        elif text.startswith('/start get_'):
            try:
                content_id_str = text.split('_')[1]
                content = content_collection.find_one({'_id': ObjectId(content_id_str)})
                if content and 'message_id_in_channel' in content:
                    wait_msg_res = requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=✅ Request received. Please wait...").json()
                    wait_msg_id = wait_msg_res.get('result', {}).get('message_id')
                    
                    payload = {'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': content['message_id_in_channel']}
                    res = requests.post(f"{TELEGRAM_API_URL}/copyMessage", json=payload)
                    
                    if wait_msg_id: requests.get(f"{TELEGRAM_API_URL}/deleteMessage?chat_id={chat_id}&message_id={wait_msg_id}")
                    if not res.json().get('ok'):
                        requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, send failed.")
                else:
                    requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, content not found.")
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=An unexpected error occurred.")
    return jsonify(status='ok')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
