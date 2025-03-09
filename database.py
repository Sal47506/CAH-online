import sqlite3
import json
from datetime import datetime
import os

# Create data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DATA_DIR, 'cah_games.db')

def init_db():
    # Create data directory if it doesn't exist
    os.makedirs(DATA_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create games table
    c.execute('''
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            state TEXT,
            round INTEGER,
            black_card TEXT,
            card_czar TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            game_data TEXT
        )
    ''')
    
    # Create players table
    c.execute('''
        CREATE TABLE IF NOT EXISTS players (
            game_id TEXT,
            player_name TEXT,
            score INTEGER,
            is_ready BOOLEAN,
            created_at TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games (game_id),
            PRIMARY KEY (game_id, player_name)
        )
    ''')
    
    conn.commit()
    conn.close()

def save_game(game_id, game_data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    now = datetime.now().isoformat()
    
    # Convert sets to lists for JSON serialization
    game_data_copy = game_data.copy()
    for key, value in game_data_copy.items():
        if isinstance(value, set):
            game_data_copy[key] = list(value)
    
    # Save game state
    c.execute('''
        INSERT OR REPLACE INTO games 
        (game_id, state, round, black_card, card_czar, game_data, updated_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, coalesce((SELECT created_at FROM games WHERE game_id = ?), ?))
    ''', (
        game_id,
        game_data_copy['state'],
        game_data_copy['round'],
        game_data_copy['black_card'],
        game_data_copy['card_czar'],
        json.dumps(game_data_copy),
        now,
        game_id,
        now
    ))
    
    # Save players
    c.executemany('''
        INSERT OR REPLACE INTO players 
        (game_id, player_name, score, is_ready, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', [
        (game_id, name, data, name in (game_data_copy['ready_players'] if isinstance(game_data_copy['ready_players'], list) else []), now)
        for name, data in game_data_copy['players'].items()
    ])
    
    conn.commit()
    conn.close()

def load_game(game_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT game_data FROM games WHERE game_id = ?', (game_id,))
    result = c.fetchone()
    
    if result:
        game_data = json.loads(result[0])
        conn.close()
        return game_data
    
    conn.close()
    return None

def delete_old_games(days=7):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        DELETE FROM players WHERE game_id IN (
            SELECT game_id FROM games 
            WHERE datetime(updated_at) < datetime('now', '-' || ? || ' days')
        )
    ''', (days,))
    
    c.execute('''
        DELETE FROM games 
        WHERE datetime(updated_at) < datetime('now', '-' || ? || ' days')
    ''', (days,))
    
    conn.commit()
    conn.close()
