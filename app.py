from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import json
import random

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
    white_cards = []
    for pack in packs:
        if "white" in pack:
            white_cards.extend([card["text"] for card in pack["white"] if "text" in card])
    return white_cards

def get_all_black_cards():
    black_cards = []
    for pack in packs:
        if "black" in pack:
            black_cards.extend([card["text"] for card in pack["black"] if "text" in card])
    return black_cards

# Game state
game_state = {
    "round": 1,
    "black_card": None,
    "players": {},  # Format: {"player_name": score}
    "submissions": {},  # Format: {"player_name": "selected_white_card"}
    "card_czar": None,
}

@app.route("/")
def home():
    print("Launching index.html")  # Debugging print
    return render_template("index.html")

@socketio.on("join_game")
def handle_join_game(data):
    player_name = data["player_name"]
    if player_name not in game_state["players"]:
        game_state["players"][player_name] = 0
        emit("update_players", game_state["players"], broadcast=True)

@socketio.on("start_round")
def handle_start_round():
    game_state["black_card"] = random.choice(get_all_black_cards())
    game_state["submissions"] = {}
    
    # Choose a random player as the Card Czar
    if game_state["players"]:
        available_players = list(game_state["players"].keys())
    
    if game_state['card_czar'] in available_players:
        available_players.remove(game_state['card_czar'])
    
    if available_players:
        game_state['card_czar'] = random.choice(available_players)
                            

    emit("new_round", {
        "black_card": game_state["black_card"],
        "card_czar": game_state["card_czar"]
    }, broadcast=True)

@socketio.on("draw_white_cards")
def handle_draw_white_cards():
    white_cards = random.sample(get_all_white_cards(), 5)
    emit("white_card_choices", {"white_cards": white_cards})

@socketio.on("submit_card")
def handle_submit_card(data):
    player_name = data["player_name"]
    selected_card = data["white_card"]
    
    if player_name in game_state["players"]:
        game_state["submissions"][player_name] = selected_card
        emit("update_submissions", game_state["submissions"], broadcast=True)

@socketio.on("judge_round")
def handle_judge_round(data):
    winner = data["winner"]
    
    if winner in game_state["players"]:
        game_state["players"][winner] += 1  # Increase winner's score
        game_state["round"] += 1  # Move to next round
        
        emit("round_winner", {
            "winner": winner,
            "score": game_state["players"][winner],
            "round": game_state["round"]
        }, broadcast=True)

if __name__ == "__main__":
    socketio.run(app, debug=True)
