import os
import re
import requests
from flask import (
    Flask, request, jsonify, abort, render_template_string, redirect, url_for, session, flash
)
from pymongo import MongoClient
from bson.objectid import ObjectId
from functools import wraps

# ======================================================================
# --- আপনার ব্যক্তিগত ও অ্যাডমিন তথ্য ---
# ======================================================================
MONGO_URI = "mongodb+srv://mesohas358:mesohas358@cluster0.6kxy1vc.mongodb.net/movie_database?retryWrites=true&w=majority&appName=Cluster0"
BOT_TOKEN = "7931162174:AAGK8aSdqoYpZ4bsSXp36dp6zbVnYeenowA"
TMDB_API_KEY = "7dc544d9253bccc3cfecc1c677f69819"
ADMIN_CHANNEL_ID = "-1002853936940"
BOT_USERNAME = "CTGVideoPlayerBot"
ADMIN_USER = "Nahid270"
ADMIN_PASS = "Nahid270"
# ======================================================================

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
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

# --- HTML এবং CSS টেমপ্লেট ---
# ... [PASTE YOUR INDEX_TEMPLATE, ADMIN_TEMPLATE, CSS_CODE HERE] ...
# DETAIL_TEMPLATE এবং PLAYER_TEMPLATE আপডেট করা হয়েছে

DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no" />
    <title>{{ content.title if content else "Not Found" }} - MovieZone</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css">
    <link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet" />
    <style>
        {{ css_code|safe }}
        .player-container { 
            position: relative; 
            width: 100%; 
            max-width: 800px;
            margin: 30px auto 20px auto;
            aspect-ratio: 16 / 9;
            background-color: #000;
        }
        .video-js { width: 100%; height: 100%; }
        .detail-info { width: 100%; max-width: 800px; margin: 0 auto; text-align: left; }
        @media (min-width: 769px) {
            .detail-content-wrapper { flex-direction: column; align-items: center; }
            .detail-poster { display: none; }
        }
    </style>
</head>
<body>
    <header class="detail-header"><a href="{{ url_for('index') }}" class="back-button"><i class="fas fa-arrow-left"></i> Back to Home</a></header>
    {% if content %}
    <div class="detail-hero" style="min-height: auto; padding: 100px 20px 60px 20px;">
      <div class="detail-hero-background" style="background-image: url('{{ content.poster_url }}');"></div>
      <div class="detail-content-wrapper">
        <div class="detail-info">
          <h1 class="detail-title">{{ content.title }}</h1>
          <div class="detail-meta">
            {% if content.release_year %}<span>{{ content.release_year }}</span>{% endif %}
            {% if content.rating %}<span><i class="fas fa-star" style="color:#f5c518;"></i> {{ "%.1f"|format(content.rating) }}</span>{% endif %}
          </div>
          <!-- Video Player Container -->
          <div class="player-container">
            <video id="my-video" class="video-js vjs-default-skin vjs-big-play-centered" controls preload="metadata" poster="{{ content.poster_url }}" data-setup='{"fluid": true}'>
            </video>
          </div>
          <p class="detail-overview">{{ content.description }}</p>
          <h5 class="mb-3">Watch or Download</h5>
          <div class="quality-buttons">
            {% if content.qualities %}
                {% for quality, data in content.qualities.items() %}
                    <button class="watch-now-btn play-btn" data-quality="{{ quality }}" style="background-color: #28a745;">
                        <i class="fas fa-play"></i> Play {{ quality }}
                    </button>
                    <a href="https://t.me/{{ bot_username }}?start=get_{{ content._id }}_{{ quality }}" class="watch-now-btn" target="_blank">
                        <i class="fas fa-robot"></i> Get {{ quality }}
                    </a>
                {% endfor %}
            {% else %}
                <p>No links available.</p>
            {% endif %}
          </div>
        </div>
      </div>
    </div>
    {% else %}
    <div style="display:flex; justify-content:center; align-items:center; height:100vh;"><h2>Content not found.</h2></div>
    {% endif %}
    <script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const player = videojs('my-video');
            const playButtons = document.querySelectorAll('.play-btn');

            function loadVideo(quality) {
                // আমরা সরাসরি একটি 'play' রাউটে যাই, যা আমাদের টেলিগ্রাম লিঙ্কে রিডাইরেক্ট করবে।
                const playUrl = `{{ url_for('play_content', content_id=content._id, quality='_') }}`.replace('_', quality);
                player.src({ src: playUrl, type: 'video/mp4' });
                player.play();
            }

            playButtons.forEach(button => {
                button.addEventListener('click', function() {
                    const quality = this.getAttribute('data-quality');
                    loadVideo(quality);
                });
            });

            // ডিফল্টভাবে প্রথম কোয়ালিটি লোড করুন, কিন্তু প্লে করবেন না।
            if (playButtons.length > 0) {
                const defaultQuality = playButtons[0].getAttribute('data-quality');
                const defaultUrl = `{{ url_for('play_content', content_id=content._id, quality='_') }}`.replace('_', defaultQuality);
                player.src({ src: defaultUrl, type: 'video/mp4' });
            }
        });
    </script>
</body>
</html>
"""

# ... [Your other functions and routes like index, admin, etc. here] ...
# ... parse_filename, get_tmdb_info, login_required ...

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if 'channel_post' in data:
        post = data['channel_post']
        if str(post['chat']['id']) == ADMIN_CHANNEL_ID:
            file = post.get('video') or post.get('document')
            if file and content_collection is not None:
                # `file_id` সেভ করা সবচেয়ে গুরুত্বপূর্ণ
                file_id = file.get('file_id')
                filename = file.get('file_name', '')
                
                parsed_info = parse_filename(filename)
                if parsed_info:
                    tmdb_data = get_tmdb_info(parsed_info)
                    if tmdb_data and tmdb_data.get('original_title'):
                        existing_content = content_collection.find_one({'original_title': tmdb_data['original_title']})
                        
                        # ডাটাবেসে message_id (ডাউনলোডের জন্য) এবং file_id (স্ট্রিমিং-এর জন্য) দুটোই সেভ করুন
                        quality_data = {
                            'message_id': post['message_id'],
                            'file_id': file_id
                        }
                        
                        if existing_content:
                            quality_key = f"qualities.{parsed_info['quality']}"
                            content_collection.update_one(
                                {'_id': existing_content['_id']},
                                {'$set': {quality_key: quality_data}}
                            )
                            print(f"SUCCESS: Updated quality '{parsed_info['quality']}' for '{existing_content['title']}'")
                        else:
                            tmdb_data['qualities'] = {parsed_info['quality']: quality_data}
                            content_collection.insert_one(tmdb_data)
                            print(f"SUCCESS: New content '{tmdb_data['title']}' saved.")
    
    elif 'message' in data:
        message = data['message']
        chat_id, text = message['chat']['id'], message.get('text', '')
        if text.startswith('/start get_'):
            try:
                parts = text.split('_')
                content_id_str, quality = parts[1], parts[2]
                content = content_collection.find_one({'_id': ObjectId(content_id_str)})
                if content and quality in content.get('qualities', {}):
                    # `message_id` ব্যবহার করে ফাইলটি কপি করুন
                    message_id = content['qualities'][quality]['message_id']
                    payload = {'chat_id': chat_id, 'from_chat_id': ADMIN_CHANNEL_ID, 'message_id': message_id}
                    requests.post(f"{TELEGRAM_API_URL}/copyMessage", json=payload)
                else: 
                    requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=Sorry, content not found.")
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                requests.get(f"{TELEGRAM_API_URL}/sendMessage?chat_id={chat_id}&text=An error occurred.")

    return jsonify(status='ok')

# === চূড়ান্ত স্ট্রিমিং রাউট (রিডাইরেক্ট পদ্ধতি) ===
@app.route('/play/<content_id>/<quality>')
def play_content(content_id, quality):
    try:
        content = content_collection.find_one({'_id': ObjectId(content_id)})
        if not content: abort(404, "Content not found")

        quality_data = content.get('qualities', {}).get(quality)
        if not quality_data or 'file_id' not in quality_data:
            abort(404, "File ID for this quality not found")
        
        file_id = quality_data['file_id']
        
        # টেলিগ্রাম API থেকে file_path পাওয়া
        r = requests.get(f"{TELEGRAM_API_URL}/getFile", params={'file_id': file_id})
        r.raise_for_status()
        file_info = r.json()

        if not file_info.get('ok'):
            abort(500, "Failed to get file info from Telegram")
            
        file_path = file_info['result']['file_path']
        
        # টেলিগ্রামের অস্থায়ী ফাইল ডাউনলোড লিঙ্ক তৈরি
        telegram_file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        # ব্যবহারকারীকে সরাসরি টেলিগ্রামের লিঙ্কে রিডাইরেক্ট করুন
        return redirect(telegram_file_url)

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error from Telegram: {e.response.text}")
        abort(502, "Error communicating with Telegram API")
    except Exception as e:
        print(f"Streaming Error: {e}")
        abort(500, "An internal error occurred")


if __name__ == '__main__':
    # আপনার বাকি রাউটগুলো এবং ফাংশনগুলো এখানে যুক্ত করতে হবে
    # যেমন: index, admin_login, admin_dashboard, etc.
    # আমি শুধুমাত্র মূল ফাংশনগুলো দেখালাম।
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
