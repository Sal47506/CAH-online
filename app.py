from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import json
import random
import string
from database import init_db, save_game, load_game, delete_old_games
import requests
from werkzeug.middleware.proxy_fix import ProxyFix
import os
from dotenv import load_dotenv
from datetime import datetime

# Get Cloudflare IP ranges
def get_cloudflare_ips():
    try:
        response = requests.get('https://api.cloudflare.com/client/v4/ips')
        if response.status_code == 200:
            return response.json()['result']['ipv4_cidrs'] + response.json()['result']['ipv6_cidrs']
        return []
    except:
        return []

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default-dev-key')
# Add Cloudflare configuration
app.config['CLOUDFLARE_IPS'] = get_cloudflare_ips()
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,      # X-Forwarded-For
    x_proto=1,    # X-Forwarded-Proto
    x_host=1,     # X-Forwarded-Host
    x_prefix=1    # X-Forwarded-Prefix
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='eventlet',
    manage_session=False,
    logger=True,
    engineio_logger=True,
    transports=['websocket', 'polling']
)

# Initialize database and clean old games at startup
with app.app_context():
    init_db()
    delete_old_games()

# Load cards from JSON file
def get_cards():
    try:
        with open("cah-all-full.json", "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            return {"error": "Invalid JSON format"}
        return data
    except FileNotFoundError:
        return {"error": "cah-all-full.json file not found"}
    except json.JSONDecodeError:
        return {"error": "Failed to parse JSON data"}

packs = get_cards()

# Extract white and black cards
def get_all_white_cards():
    return [card["text"] for pack in packs if "white" in pack for card in pack["white"] if "text" in card]

def get_all_black_cards():
    return [card["text"] for pack in packs if "black" in pack for card in pack["black"] if "text" in card]

# Store game rooms
game_rooms = {}  # Format: {"ABC123": {"players": {}, "black_card": None, "submissions": {}, "card_czar": None, "round": 1, "state": "waiting", "disconnected_players": {}, "min_players": 3, "round_timer": None, "ready_players": set(), "player_hands": {}}}

# Generate a unique game ID
def generate_game_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/create_game", methods=["POST"])
def create_game():
    game_id = generate_game_id()
    game_data = {
        "round": 1,
        "black_card": None,
        "players": {},
        "submissions": {},
        "card_czar": None,
        "state": "waiting",
        "disconnected_players": {},
        "min_players": 3,
        "round_timer": None,
        "ready_players": [],  # Changed from set() to []
        "player_hands": {},
        "score_limit": 8,
        "round_time_limit": 120,
        "spectators": [],  # Changed from set() to []
        "used_cards": [],  # Changed from set() to []
        "game_winner": None,
        "max_rounds": 10,  # Add max rounds limit
    }
    
    game_rooms[game_id] = game_data
    save_game(game_id, game_data)
    return redirect(url_for("game_room", game_id=game_id))

@app.route("/game/<game_id>")
def game_room(game_id):
    # Try to load game from database if not in memory
    if game_id not in game_rooms:
        game_data = load_game(game_id)
        if game_data:
            game_rooms[game_id] = game_data
        else:
            return "Game not found", 404
    return render_template("game.html", game_id=game_id)

@app.route("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}, 200

@socketio.on_error()
def error_handler(e):
    print('An error has occurred:', e)
    emit('error', {'message': 'An error occurred'})

@socketio.on_error_default
def default_error_handler(e):
    print('An error has occurred:', e)
    emit('error', {'message': 'An error occurred'})

@socketio.on('disconnect')
def handle_disconnect(*args):
    sid = request.sid
    print('Client disconnected:', sid)
    
    # Find and remove disconnected player
    for game_id in game_rooms:
        for player_name in list(game_rooms[game_id]["players"].keys()):
            if getattr(request, 'sid_' + player_name, None) == sid:
                # Store player's score before removing
                game_rooms[game_id]["disconnected_players"][player_name] = game_rooms[game_id]["players"][player_name]
                del game_rooms[game_id]["players"][player_name]
                print(f'Player {player_name} disconnected from game {game_id}')
                
                # Notify other players
                emit("update_players", {
                    "players": game_rooms[game_id]["players"],
                    "min_players": game_rooms[game_id]["min_players"],
                    "state": game_rooms[game_id]["state"],
                    "disconnected": list(game_rooms[game_id]["disconnected_players"].keys())
                }, room=game_id)
                return

# Update existing socket handlers with error handling
@socketio.on("join_game")
def handle_join_game(data):
    try:
        game_id = data["game_id"]
        player_name = data["player_name"]
        
        if game_id in game_rooms:
            # Store socket ID for this player
            setattr(request, 'sid_' + player_name, request.sid)
            
            # Check if player was previously disconnected
            if player_name in game_rooms[game_id]["disconnected_players"]:
                game_rooms[game_id]["players"][player_name] = game_rooms[game_id]["disconnected_players"][player_name]
                del game_rooms[game_id]["disconnected_players"][player_name]
            elif player_name not in game_rooms[game_id]["players"]:
                game_rooms[game_id]["players"][player_name] = 0
            
            join_room(game_id)
            emit("update_players", {
                "players": game_rooms[game_id]["players"],
                "min_players": game_rooms[game_id]["min_players"],
                "state": game_rooms[game_id]["state"]
            }, room=game_id)
            
            # Send current game state if game is in progress
            if game_rooms[game_id]["state"] != "waiting":
                emit("game_state", {
                    "black_card": game_rooms[game_id]["black_card"],
                    "card_czar": game_rooms[game_id]["card_czar"],
                    "round": game_rooms[game_id]["round"],
                    "submitted_players": list(game_rooms[game_id]["submissions"].keys())
                })
            
            # Save game state after player joins
            save_game(game_id, game_rooms[game_id])
            
        else:
            emit("error", {"message": "Game not found"})
    except Exception as e:
        print('Error in join_game:', e)
        emit("error", {"message": "Failed to join game"})

@socketio.on("start_round")
def handle_start_round(data):
    game_id = data["game_id"]
    if game_id in game_rooms:
        if len(game_rooms[game_id]["players"]) < game_rooms[game_id]["min_players"]:
            emit("error", {
                "message": f"Need at least {game_rooms[game_id]['min_players']} players to start"
            }, room=game_id)
            return
            
        # Check if all players are ready
        all_ready = len(game_rooms[game_id]["ready_players"]) == len(game_rooms[game_id]["players"])
        if not all_ready:
            emit("error", {
                "message": "All players must be ready to start"
            }, room=game_id)
            return

        game_rooms[game_id]["state"] = "in_progress"
        game_rooms[game_id]["black_card"] = random.choice(get_all_black_cards())
        game_rooms[game_id]["submissions"] = {}

        available_players = list(game_rooms[game_id]["players"].keys())
        if game_rooms[game_id]["card_czar"] in available_players:
            available_players.remove(game_rooms[game_id]["card_czar"])
        if available_players:
            game_rooms[game_id]["card_czar"] = random.choice(available_players)

        emit("new_round", {
            "black_card": game_rooms[game_id]["black_card"],
            "card_czar": game_rooms[game_id]["card_czar"],
            "game_started": True
        }, room=game_id)

@socketio.on("draw_white_cards")
def handle_draw_white_cards(data):
    game_id = data["game_id"]
    player_name = data.get("player_name")
    card_czar = data.get("card_czar")

    if player_name == card_czar:
        return
    
    if game_id in game_rooms:
        # Initialize player_hands if not exists
        if "player_hands" not in game_rooms[game_id]:
            game_rooms[game_id]["player_hands"] = {}
        
        # Initialize used_cards if not exists
        if "used_cards" not in game_rooms[game_id]:
            game_rooms[game_id]["used_cards"] = []
            
        all_white_cards = get_all_white_cards()
        available_cards = [card for card in all_white_cards if card not in game_rooms[game_id]["used_cards"]]
        
        # If we're running low on cards, reset the used cards
        if len(available_cards) < 5:
            game_rooms[game_id]["used_cards"].clear()
            available_cards = all_white_cards
            
        # Draw 5 unique cards for the player
        if player_name != card_czar:
            new_cards = random.sample(available_cards, 5)
            game_rooms[game_id]["player_hands"][player_name] = new_cards
            game_rooms[game_id]["used_cards"].extend([card for card in new_cards 
                                                    if card not in game_rooms[game_id]["used_cards"]])
        
        # Only send cards to the requesting player
        emit("white_card_choices", {
            "white_cards": new_cards
        }, room=request.sid)

@socketio.on("submit_card")
def handle_submit_card(data):
    try:
        game_id = data["game_id"]
        player_name = data["player_name"]
        selected_card = data["white_card"]

        if game_id in game_rooms and player_name in game_rooms[game_id]["players"]:
            # Store the submission
            game_rooms[game_id]["submissions"][player_name] = selected_card
            
            # Broadcast submissions to all players (card czar will filter on client side)
            emit("update_submissions", {
                "submissions": game_rooms[game_id]["submissions"],
                "card_czar": game_rooms[game_id]["card_czar"]
            }, room=game_id)
            
            print(f"Submission received from {player_name}: {selected_card}")
            print(f"Current submissions: {game_rooms[game_id]['submissions']}")
    except Exception as e:
        print(f"Error in submit_card: {str(e)}")
        emit("error", {"message": "Failed to submit card"})

@socketio.on("judge_round")
def handle_judge_round(data):
    try:
        game_id = data.get("game_id")
        winner = data.get("winner")
        winning_card = data.get("winning_card")

        if not all([game_id, winner, winning_card]):
            raise ValueError("Missing required data for judging round")

        if game_id not in game_rooms:
            raise ValueError("Game not found")

        # Update game state
        game_rooms[game_id]["players"][winner] += 1
        game_rooms[game_id]["round"] += 1  # Increment round number
        game_rooms[game_id]["submissions"] = {}

        # Check if we've reached max rounds
        if game_rooms[game_id]["round"] > game_rooms[game_id]["max_rounds"]:
            # Find the winner
            winner = max(game_rooms[game_id]["players"].items(), key=lambda x: x[1])[0]
            game_rooms[game_id]["game_winner"] = winner
            emit("game_over", {
                "winner": winner,
                "final_scores": game_rooms[game_id]["players"],
                "reason": "Maximum rounds reached"
            }, room=game_id)
            return

        # Emit round winner with updated round number
        emit("round_winner", {
            "winner": winner,
            "winning_card": winning_card,
            "score": game_rooms[game_id]["players"][winner],
            "round": game_rooms[game_id]["round"]  # Include round number
        }, room=game_id)

        # Update all players with new game state
        emit("update_game_state", {
            "players": game_rooms[game_id]["players"],
            "round": game_rooms[game_id]["round"],
            "state": game_rooms[game_id]["state"]
        }, room=game_id)
        
        # Save game state after round ends
        save_game(game_id, game_rooms[game_id])

    except Exception as e:
        print(f"Error in judge_round: {str(e)}")
        emit("error", {"message": f"Failed to judge round: {str(e)}"}, room=game_id)

@socketio.on("chat_message")
def handle_chat_message(data):
    try:
        game_id = data.get("game_id")
        player = data.get("player")
        message = data.get("message")

        if not all([game_id, player, message]):
            raise ValueError("Missing required chat data")

        if game_id in game_rooms:
            emit("chat_message", {
                "player": player,
                "message": message
            }, room=game_id)
    except Exception as e:
        print(f"Error in chat_message: {str(e)}")
        emit("error", {"message": "Failed to send chat message"})

@socketio.on("player_ready")
def handle_player_ready(data):
    try:
        game_id = data["game_id"]
        player_name = data["player_name"]
        is_ready = data.get("is_ready", True)
        
        if game_id in game_rooms:
            ready_players = game_rooms[game_id]["ready_players"]
            if isinstance(ready_players, set):
                ready_players = list(ready_players)
                
            if is_ready and player_name not in ready_players:
                ready_players.append(player_name)
            elif not is_ready and player_name in ready_players:
                ready_players.remove(player_name)
                
            game_rooms[game_id]["ready_players"] = ready_players
            
            all_ready = len(ready_players) == len(game_rooms[game_id]["players"])
            
            emit("update_ready_players", {
                "ready_players": ready_players,
                "all_ready": all_ready
            }, room=game_id)

    except Exception as e:
        print(f"Error in player_ready: {str(e)}")
        emit("error", {"message": "Failed to set player ready status"})

@socketio.on("status_message")
def handle_status_message(data):
    try:
        game_id = data["game_id"]
        message = data["message"]
        emit("status_message", {"message": message}, room=game_id)
    except Exception as e:
        print(f"Error in status_message: {str(e)}")

@socketio.on("check_game_end")
def check_game_end(game_id):
    if game_id in game_rooms:
        for player, score in game_rooms[game_id]["players"].items():
            if score >= game_rooms[game_id]["score_limit"]:
                game_rooms[game_id]["game_winner"] = player
                emit("game_over", {
                    "winner": player,
                    "final_scores": game_rooms[game_id]["players"]
                }, room=game_id)
                return True
    return False

@socketio.on("join_as_spectator")
def handle_spectator(data):
    game_id = data["game_id"]
    spectator_name = data["spectator_name"]
    if game_id in game_rooms:
        game_rooms[game_id]["spectators"].add(spectator_name)
        join_room(game_id)
        emit("spectator_joined", {"name": spectator_name}, room=game_id)

# Add security headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# Rate limiting for specific endpoints
def get_real_ip():
    if request.headers.get('CF-Connecting-IP'):
        return request.headers.get('CF-Connecting-IP')
    return request.remote_addr

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
