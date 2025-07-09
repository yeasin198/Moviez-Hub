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
BOT_USERNAME = "CTGVideoPlayerBot"
# ======================================================================

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- অ্যাপ এবং ডাটাবেস সংযোগ ---
app = Flask(__name__)
try:
    client = MongoClient(MONGO_URI)
    db = client.get_database() 
    content_collection = db.content # কালেকশনের নাম পরিবর্তন করে 'content' করা হলো
    client.admin.command('ping')
    print("SUCCESS: MongoDB Connected Successfully!")
except Exception as e:
    print(f"FATAL: Could not connect to MongoDB. Error: {e}")
    content_collection = None

# --- HTML এবং CSS টেমপ্লেট (অপরিবর্তিত) ---
TEMPLATES = {
    # আগের উত্তর থেকে base, index, detail টেমপ্লেটের কোড এখানে কপি করুন
    "base": """...""", "index": """...""", "detail": """..."""
}
CSS_CODE = """..."""
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

# --- নতুন এবং উন্নত হেল্পার ফাংশন ---
def parse_filename(filename):
    """ফাইলের নাম থেকে মুভি বা সিরিজের তথ্য বের করে।"""
    cleaned_name = filename.replace('.', ' ').replace('_', ' ')
    
    # সিরিজের ফরম্যাট চেক করা হচ্ছে (e.g., S01E01)
    series_match = re.search(r'^(.*?)[\s\._-]*[sS](\d+)[eE](\d+)', cleaned_name, re.IGNORECASE)
    if series_match:
        series_name = series_match.group(1).strip()
        season_num = int(series_match.group(2))
        episode_num = int(series_match.group(3))
        return {
            'type': 'tv', 'title': series_name, 
            'season': season_num, 'episode': episode_num
        }
    
    # মুভির ফরম্যাট চেক করা হচ্ছে (e.g., (2023))
    movie_match = re.search(r'^(.*?)\s*\(?(\d{4})\)?', cleaned_name, re.IGNORECASE)
    if movie_match:
        movie_title = movie_match.group(1).strip()
        year = movie_match.group(2).strip()
        return {'type': 'movie', 'title': movie_title, 'year': year}
        
    return None

def get_tmdb_info(parsed_info):
    """TMDb থেকে মুভি বা সিরিজের তথ্য সংগ্রহ করে।"""
    content_type = parsed_info['type']
    
    if content_type == 'movie':
        api_url = "https://api.themoviedb.org/3/search/movie"
        params = {'api_key': TMDB_API_KEY, 'query': parsed_info['title'], 'primary_release_year': parsed_info['year']}
    elif content_type == 'tv':
        api_url = "https://api.themoviedb.org/3/search/tv"
        params = {'api_key': TMDB_API_KEY, 'query': parsed_info['title']}
    else:
        return None

    try:
        r = requests.get(api_url, params=params)
        r.raise_for_status()
        res = r.json()
        if res.get('results'):
            data = res['results'][0]
            if content_type == 'movie':
                title = data.get('title')
                year = data.get('release_date', '')[:4]
            else: # TV Series
                title = f"{data.get('name')} S{parsed_info['season']:02d}E{parsed_info['episode']:02d}"
                year = data.get('first_air_date', '')[:4]
                
            poster = data.get('poster_path')
            return {
                'type': content_type, 'title': title, 'description': data.get('overview'),
                'poster_url': f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                'release_year': year, 'rating': round(data.get('vote_average', 0), 1)
            }
    except requests.exceptions.RequestException as e: 
        print(f"Error fetching TMDb info: {e}")
    return None


# --- Flask রাউট ---
@app.route('/')
def index():
    if content_collection is None: return "Database connection failed.", 500
    all_content = list(content_collection.find().sort('_id', -1))
    return render_template('index', movies=all_content) # টেমপ্লেটে এখনও movies নামেই পাঠানো হচ্ছে

@app.route('/movie/<content_id>') # URL পরিবর্তন করে content_id করা হলো
def content_detail(content_id):
    if content_collection is None: return "Database connection failed.", 500
    try:
        content = content_collection.find_one({'_id': ObjectId(content_id)})
        if content: return render_template('detail', movie=content) # movie নামেই পাঠানো হচ্ছে
        else: abort(404)
    except: abort(404)


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
                    print(f"Parsed info: {parsed_info}")
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
            requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Welcome! Browse our website to get content.")
        
        # --- ফাইল পাঠানোর লজিক ---
        # URL এ file_ এর বদলে content_ ব্যবহার করা হচ্ছে
        elif text.startswith('/start content_'):
            try:
                content_id_str = text.split('_')[1]
                content = content_collection.find_one({'_id': ObjectId(content_id_str)})
                if content and 'message_id_in_channel' in content:
                    wait_msg = requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=✅ Request received...").json()
                    wait_msg_id = wait_msg.get('result', {}).get('message_id')
                    
                    payload = {'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': content['message_id_in_channel']}
                    res = requests.post(f"{TELEGRAM_API_URL}/copyMessage", json=payload)
                    
                    if wait_msg_id: requests.get(f"{TELEGRAM_API_URL}/deleteMessage?chat_id={chat_id}&message_id={wait_msg_id}")
                    
                    if not res.json().get('ok'):
                        error_desc = res.json().get('description', 'Unknown error')
                        requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, send failed: {error_desc}")
                else:
                    requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, content not found.")
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=An unexpected error occurred.")
                
    return jsonify(status='ok')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
