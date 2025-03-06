from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import json
import random
import string

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

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
game_rooms = {}  # Format: {"ABC123": {"players": {}, "black_card": None, "submissions": {}, "card_czar": None, "round": 1}}

# Generate a unique game ID
def generate_game_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/create_game", methods=["POST"])
def create_game():
    game_id = generate_game_id()
    game_rooms[game_id] = {
        "round": 1,
        "black_card": None,
        "players": {},
        "submissions": {},
        "card_czar": None,
    }
    return redirect(url_for("game_room", game_id=game_id))

@app.route("/game/<game_id>")
def game_room(game_id):
    if game_id not in game_rooms:
        return "Game not found", 404
    return render_template("game.html", game_id=game_id)

@socketio.on_error()
def error_handler(e):
    print('An error has occurred:', e)
    emit('error', {'message': 'An error occurred'})

@socketio.on_error_default
def default_error_handler(e):
    print('An error has occurred:', e)
    emit('error', {'message': 'An error occurred'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    # Clean up any necessary game state here

# Update existing socket handlers with error handling
@socketio.on("join_game")
def handle_join_game(data):
    try:
        game_id = data["game_id"]
        player_name = data["player_name"]
        
        if game_id in game_rooms:
            if player_name not in game_rooms[game_id]["players"]:
                game_rooms[game_id]["players"][player_name] = 0
                join_room(game_id)
            emit("update_players", game_rooms[game_id]["players"], room=game_id)
        else:
            emit("error", {"message": "Game not found"})
    except Exception as e:
        print('Error in join_game:', e)
        emit("error", {"message": "Failed to join game"})

@socketio.on("start_round")
def handle_start_round(data):
    game_id = data["game_id"]
    if game_id in game_rooms:
        game_rooms[game_id]["black_card"] = random.choice(get_all_black_cards())
        game_rooms[game_id]["submissions"] = {}

        available_players = list(game_rooms[game_id]["players"].keys())
        if game_rooms[game_id]["card_czar"] in available_players:
            available_players.remove(game_rooms[game_id]["card_czar"])
        if available_players:
            game_rooms[game_id]["card_czar"] = random.choice(available_players)

        emit("new_round", {
            "black_card": game_rooms[game_id]["black_card"],
            "card_czar": game_rooms[game_id]["card_czar"]
        }, room=game_id)

@socketio.on("draw_white_cards")
def handle_draw_white_cards(data):
    game_id = data["game_id"]
    if game_id in game_rooms:
        white_cards = random.sample(get_all_white_cards(), 5)
        emit("white_card_choices", {"white_cards": white_cards}, room=game_id)

@socketio.on("submit_card")
def handle_submit_card(data):
    game_id = data["game_id"]
    player_name = data["player_name"]
    selected_card = data["white_card"]

    if game_id in game_rooms and player_name in game_rooms[game_id]["players"]:
        game_rooms[game_id]["submissions"][player_name] = selected_card
        emit("update_submissions", game_rooms[game_id]["submissions"], room=game_id)

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

        if winner not in game_rooms[game_id]["players"]:
            raise ValueError("Winner not found in game")

        # Update winner's score
        game_rooms[game_id]["players"][winner] += 1
        game_rooms[game_id]["round"] += 1
        game_rooms[game_id]["submissions"] = {}  # Clear submissions for next round

        # First emit round winner
        emit("round_winner", {
            "winner": winner,
            "winning_card": winning_card,
            "score": game_rooms[game_id]["players"][winner],
            "round": game_rooms[game_id]["round"]
        }, room=game_id)

        # Then broadcast updated scores to all players
        emit("update_players", game_rooms[game_id]["players"], room=game_id)

    except Exception as e:
        print(f"Error in judge_round: {str(e)}")
        emit("error", {"message": f"Failed to judge round: {str(e)}"}, room=game_id)

if __name__ == "__main__":
    socketio.run(app, debug=True)
