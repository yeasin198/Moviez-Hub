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
    client = MongoClient(MONGO_URI)
    db = client.get_database() 
    movies_collection = db.movies
    client.admin.command('ping') # সংযোগ পরীক্ষা করার জন্য
    print("MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")
    movies_collection = None

# --- হেল্পার ফাংশন ---
def parse_movie_name(filename):
    """ফাইলের নাম থেকে মুভির নাম এবং সাল বের করে।"""
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name)
    if match:
        title = match.group(1).strip()
        year = match.group(2).strip()
        return title, year
    return None, None

def get_tmdb_info(title, year):
    """TMDb API থেকে মুভির তথ্য সংগ্রহ করে।"""
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
    """টেলিগ্রাম থেকে ফাইলের একটি সাময়িক ডাউনলোড লিঙ্ক তৈরি করে।"""
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
    if not movies_collection: return "Database connection failed. Please check your MongoDB URI.", 500
    all_movies = list(movies_collection.find().sort('_id', -1))
    return render_template('index.html', movies=all_movies)

@app.route('/movie/<movie_id>')
def movie_detail(movie_id):
    if not movies_collection: return "Database connection failed.", 500
    try:
        movie = movies_collection.find_one({'_id': ObjectId(movie_id)})
        if movie: return render_template('movie_detail.html', movie=movie)
        else: abort(404)
    except Exception:
        abort(404)

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    if not movies_collection:
        print("Webhook skipped: Database not connected.")
        return jsonify(status='failed', reason='db_connection_error')

    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        chat_id = str(post['chat']['id'])
        
        if chat_id == ADMIN_CHANNEL_ID and ('video' in post or 'document' in post):
            file_info = post.get('video') or post.get('document')
            if not file_info: return jsonify(status='ok')

            file_id = file_info['file_id']
            file_name = file_info.get('file_name', 'Untitled')
            
            title, year = parse_movie_name(file_name)
            if not title or not year:
                print(f"ERROR: Could not parse title/year from '{file_name}'")
                return jsonify(status='failed', reason='parsing_error')

            movie_info = get_tmdb_info(title, year)
            if not movie_info:
                print(f"ERROR: TMDb info not found for '{title} ({year})'")
                return jsonify(status='failed', reason='tmdb_not_found')
            
            download_url = get_telegram_file_link(file_id)
            if not download_url:
                print(f"ERROR: Could not get download link for file_id '{file_id}'")
                return jsonify(status='failed', reason='telegram_link_error')

            movie_document = {
                'title': movie_info['title'],
                'description': movie_info['description'],
                'poster_url': movie_info['poster_url'],
                'release_year': movie_info['release_year'],
                'rating': movie_info['rating'],
                'download_url': download_url
            }
            movies_collection.insert_one(movie_document)
            print(f"SUCCESS: Movie '{movie_info['title']}' added to database.")
    
    return jsonify(status='ok')

if __name__ == '__main__':
    # Render.com এর জন্য প্রয়োজনীয় কনফিগারেশন
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
