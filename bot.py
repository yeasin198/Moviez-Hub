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
BOT_USERNAME = "Mtest100bot" # <-- এখানে আপনার বটের সঠিক ইউজারনেমটি বসান
# ======================================================================

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

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

# --- HTML এবং CSS টেমপ্লেট (অপরিবর্তিত) ---
TEMPLATES = { "base": """...""", "index": """...""", "detail": """...""" } # আগের কোড থেকে কপি করুন, এখানে আর পেস্ট করছি না।
CSS_CODE = """...""" # আগের কোড থেকে কপি করুন।

# এখানে আগের উত্তরের templates এবং css কোডগুলো থাকবে। আমি জায়গা বাঁচানোর জন্য কোডটি এখানে tekrar লিখছি না।
# অনুগ্রহ করে আগের উত্তর থেকে TEMPLATES এবং CSS_CODE ভেরিয়েবলের কন্টেন্ট এখানে কপি করে নিন।

class DictLoader(BaseLoader):
    def __init__(self, templates): self.templates = templates
    def get_source(self, environment, template):
        if template in self.templates: return self.templates[template], None, lambda: True
        raise TemplateNotFound(template)

jinja_env = Environment(loader=DictLoader(TEMPLATES))
def render_template(template_name, **context):
    template = jinja_env.get_template(template_name)
    return template.render(css_code=CSS_CODE, bot_username=BOT_USERNAME, **context)


# --- হেল্পার ফাংশন (অপরিবর্তিত) ---
def parse_movie_name(filename):
    # ... আগের কোড
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name, re.IGNORECASE)
    if match: return match.group(1).strip(), match.group(2).strip()
    return None, None

def get_tmdb_info(title, year):
    # ... আগের কোড
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


# --- Flask রাউট (অপরিবর্তিত) ---
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


# --- টেলিগ্রাম বট এর মূল লজিক (সম্পূর্ণ নতুন এবং ফিক্সড) ---
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()

    # --- নতুন মুভি অ্যাড করার লজিক ---
    if 'channel_post' in data:
        post = data['channel_post']
        if str(post['chat']['id']) == ADMIN_CHANNEL_ID:
            file = post.get('video') or post.get('document')
            if file:
                title, year = parse_movie_name(file.get('file_name', ''))
                if title and year and movies_collection is not None:
                    info = get_tmdb_info(title, year)
                    if info:
                        info['file_id'] = file['file_id']
                        # === নতুন সংযোজন: message_id সেভ করা হচ্ছে ===
                        info['message_id_in_channel'] = post['message_id']
                        movies_collection.insert_one(info)
                        print(f"SUCCESS: Movie '{info['title']}' info saved with message_id.")
    
    # --- ব্যবহারকারীকে ফাইল পাঠানোর লজিক ---
    elif 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')

        # '/start' কমান্ড হ্যান্ডেল করা
        if text == '/start':
            requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Welcome! Please browse our website to get movies.")
            return jsonify(status='ok')
        
        # '/start file_...' কমান্ড হ্যান্ডেল করা
        if text.startswith('/start file_'):
            try:
                movie_id_str = text.split('_')[1]
                movie = movies_collection.find_one({'_id': ObjectId(movie_id_str)})
                
                if movie and 'message_id_in_channel' in movie:
                    from_chat_id = ADMIN_CHANNEL_ID
                    message_id = movie['message_id_in_channel']

                    # ব্যবহারকারীকে একটি "waiting" মেসেজ পাঠানো হচ্ছে
                    wait_msg = requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=✅ Request received. Please wait while we process your file...").json()
                    wait_msg_id = wait_msg.get('result', {}).get('message_id')

                    # === মূল সমাধান: copyMessage ব্যবহার করা ===
                    # এই মেথডটি ফাইল ফরওয়ার্ড করার চেয়ে বেশি নির্ভরযোগ্য
                    copy_message_url = f"{TELEGRAM_API_URL}/copyMessage"
                    payload = {
                        'chat_id': chat_id,
                        'from_chat_id': from_chat_id,
                        'message_id': message_id,
                        'reply_markup': { 'inline_keyboard': [[{ 'text': 'Visit Our Website', 'url': 'https://teest100.onrender.com' }]] }
                    }
                    res = requests.post(copy_message_url, json=payload)
                    
                    # "waiting" মেসেজটি ডিলিট করে দেওয়া হচ্ছে
                    if wait_msg_id:
                        requests.get(f"{TELEGRAM_API_URL}/deleteMessage?chat_id={chat_id}&message_id={wait_msg_id}")

                    if not res.json().get('ok'):
                        # যদি কোনো কারণে ফাইল পাঠানো না যায়
                        error_description = res.json().get('description', 'Unknown error')
                        print(f"Failed to send file. Error: {error_description}")
                        requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, we couldn't send the file. Reason: {error_description}")
                else:
                    requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, the file could not be found. It might have been deleted.")

            except Exception as e:
                # অপ্রত্যাশিত কোনো ভুলের জন্য এই মেসেজটি দেখানো হবে
                print(f"CRITICAL ERROR sending file: {e}")
                requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=An unexpected error occurred. The developer has been notified.")

    return jsonify(status='ok')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
