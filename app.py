try:
    from flask import Flask, render_template, request, redirect, url_for
    from flask_socketio import SocketIO, emit, join_room
    import json
    import random
    import string
    import openai
    import os
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Error importing required packages: {e}")
    print("Please run: pip install -r requirements.txt")
    exit(1)

load_dotenv() 

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

game_rooms = {}  # {"ABC123": {"players": {}, "black_card": None, "submissions": {}, "card_czar": None, "round": 1, "ai_czar": False}}

# Generate a unique game ID
def generate_game_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

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
    "ai_czar": False,
    "api_keys": {},  # Store API keys for each player
}

@app.route("/")
def home():
    print("Launching index.html")  # Debugging print
    return render_template("index.html")

@app.route("/create_game")
def create_game():
    game_id = generate_game_id()
    game_rooms[game_id] = game_state.copy()
    return redirect(url_for("game_room", game_id=game_id))

@app.route("/game/<game_id>")
def game_room(game_id):
    if game_id not in game_rooms:
        return "Game not found", 404
    return render_template("game.html", game_id=game_id)

@socketio.on("join_game")
def handle_join_game(data):
    player_name = data["player_name"]
    api_key = data.get("api_key", "")
    
    if player_name not in game_state["players"]:
        game_state["players"][player_name] = 0
        if api_key:
            game_state["api_keys"][player_name] = api_key
        emit("update_players", game_state["players"], broadcast=True)

@socketio.on("start_round")
def handle_start_round(data):
    game_id = data["game_id"]
    if game_id in game_rooms:
        game_rooms[game_id]["black_card"] = random.choice(get_all_black_cards())
        game_rooms[game_id]["submissions"] = {}
    
        if game_rooms[game_id]["ai_czar"]:
            game_rooms[game_id]["card_czar"] = "AI Czar"
        else:
            available_players = list(game_rooms[game_id]["players"].keys())
            game_rooms[game_id]["card_czar"] = random.choice(available_players)
        
        game_rooms[game_id]["round"] = 1

    emit("new_round", {
        "black_card": game_state["black_card"],
        "card_czar": game_state["card_czar"]
    }, broadcast=True)

@socketio.on("toggle_ai_czar")
def handle_toggle_ai_czar(data):
    game_id = data["game_id"]
    if game_id in game_rooms:
        game_rooms[game_id]["ai_czar"] = data["enabled"]
        emit("ai_czar_status", {"enabled": data["enabled"]}, room=game_id)

@socketio.on("draw_white_cards")
def handle_draw_white_cards(data):
    game_id = data["game_id"]
    game_rooms[game_id]['white_card'] = random.sample(get_all_white_cards(), 5)
    emit("white_card_choices", {"white_cards": game_rooms[game_id]['white_card']})

@socketio.on("submit_card")
def handle_submit_card(data):
    game_id = data["game_id"]
    player_name = data["player_name"]
    selected_card = data["white_card"]
    
    if game_id in game_rooms and player_name in game_rooms[game_id]["players"]:
        game_rooms[game_id]["submissions"][player_name] = selected_card
        emit("update_submissions", game_rooms[game_id]["submissions"][player_name], broadcast=True)

def ai_judge_submissions(black_card, submissions, api_key):
    if not api_key:
        return None, "No API key provided for AI Czar"
    
    try:
        client = openai.OpenAI(api_key=api_key)
        prompt = f"""As a judge in Cards Against Humanity, choose the funniest response.
        The black card is: "{black_card}"
        The submitted white cards are:
        {', '.join([f'"{card}"' for card in submissions.values()])}
        
        Pick the winner and explain why it's the funniest in one sentence.
        Response format: winning_card|explanation"""
        
        response = client.completions.create(
            model="gpt-4-turbo",
            prompt=prompt,
            max_tokens=100,
            temperature=0.7
        )
        
        winner_card, explanation = response.choices[0].text.strip().split('|')
        winner = [player for player, card in submissions.items() if card == winner_card.strip()][0]
        return winner, explanation
    except Exception as e:
        return None, f"AI Czar error: {str(e)}"

@socketio.on("judge_round")
def handle_judge_round(data):
    game_id = data["game_id"]
    
    if game_id in game_rooms:
        if game_rooms[game_id]["ai_czar"]:
            # Get API key of the player who enabled AI Czar
            current_czar = game_rooms[game_id]["card_czar"]
            api_key = game_state["api_keys"].get(current_czar, "")
            
            winner, explanation = ai_judge_submissions(
                game_rooms[game_id]["black_card"],
                game_rooms[game_id]["submissions"],
                api_key
            )
            
            if not winner:
                emit("error", {"message": explanation}, room=game_id)
                return
        else:
            winner = data["winner"]
            explanation = None
        
        game_rooms[game_id]["players"][winner] += 1
        game_rooms[game_id]["round"] += 1
        
        emit("round_winner", {
            "winner": winner,
            "explanation": explanation,
            "score": game_rooms[game_id]["players"][winner],
            "round": game_rooms[game_id]["round"]
        }, room=game_id)

if __name__ == "__main__":
    socketio.run(app, debug=True)
