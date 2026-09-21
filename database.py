import os
import csv
import io
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import libsql

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")
LOCAL_DB = "badminton.db"

#DB_PATH = "badminton.db"

PLAYERS = {
    "TH": "Thomas Heidelbach",
    "KH": "Kim Heidelbach",
    "KP": "Kim Petersen",
    "JA": "Jørgen Andersen"
}

def get_conn():
    if TURSO_URL and TURSO_TOKEN:
        conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
        conn.row_factory = sqlite3.Row
        return conn
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_date TEXT NOT NULL,
            match_type TEXT NOT NULL,       -- 'single' eller 'double'
            team1 TEXT NOT NULL,            -- F.eks. 'TH' eller 'KH & JA'
            team2 TEXT NOT NULL,            -- F.eks. 'KH' eller 'TH & KP'
            target_sets INTEGER NOT NULL    -- 3 eller 5
        );

        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            set_number INTEGER NOT NULL,
            score1 INTEGER NOT NULL,
            score2 INTEGER NOT NULL
        );
        """)

def add_match(match_date: str, match_type: str, team1: str, team2: str, target_sets: int, scores: List[Tuple[int, int]]) -> int:
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO matches (match_date, match_type, team1, team2, target_sets) VALUES (?, ?, ?, ?, ?)",
            (match_date, match_type, team1, team2, target_sets)
        )
        match_id = cursor.lastrowid
        for idx, (s1, s2) in enumerate(scores, start=1):
            cursor.execute(
                "INSERT INTO sets (match_id, set_number, score1, score2) VALUES (?, ?, ?, ?)",
                (match_id, idx, s1, s2)
            )
        return match_id

def update_match(match_id: int, match_date: str, scores: List[Tuple[int, int]]) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE matches SET match_date = ? WHERE id = ?", (match_date, match_id))
        for idx, (s1, s2) in enumerate(scores, start=1):
            conn.execute(
                "UPDATE sets SET score1 = ?, score2 = ? WHERE match_id = ? AND set_number = ?",
                (s1, s2, match_id, idx)
            )

def delete_match(match_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))

def get_all_matches() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM matches ORDER BY match_date DESC, id DESC").fetchall()
        result = []
        for r in rows:
            m = dict(r)
            s_rows = conn.execute("SELECT score1, score2 FROM sets WHERE match_id = ? ORDER BY set_number", (m["id"],)).fetchall()
            m["sets"] = [(s["score1"], s["score2"]) for s in s_rows]

            # Udregn sætvinder
            s1_wins = sum(1 for s in m["sets"] if s[0] > s[1])
            s2_wins = sum(1 for s in m["sets"] if s[1] > s[0])
            m["winner"] = m["team1"] if s1_wins > s2_wins else m["team2"]
            m["set_score"] = f"{s1_wins}-{s2_wins}"
            result.append(m)
        return result

def get_match_by_id(match_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        m_row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not m_row:
            return None
        m = dict(m_row)
        s_rows = conn.execute("SELECT score1, score2 FROM sets WHERE match_id = ? ORDER BY set_number", (match_id,)).fetchall()
        m["sets"] = [(s["score1"], s["score2"]) for s in s_rows]
        return m

def calculate_stats(filter_type: str = "all") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    matches = get_all_matches()
    # Kronologisk sortering for korrekt Elo-beregning
    chronological_matches = sorted(matches, key=lambda x: (x["match_date"], x["id"]))

    stats = {
        code: {
            "code": code,
            "name": PLAYERS.get(code, code),
            "elo": 1000.0,
            "matches_played": 0,
            "matches_won": 0,
            "matches_lost": 0,
            "sets_won": 0,
            "sets_lost": 0,
            "points_won": 0,
            "points_lost": 0,
        }
        for code in PLAYERS.keys()
    }

    def ensure_player(code: str):
        if code not in stats:
            stats[code] = {
                "code": code,
                "name": code,
                "elo": 1000.0,
                "matches_played": 0,
                "matches_won": 0,
                "matches_lost": 0,
                "sets_won": 0,
                "sets_lost": 0,
                "points_won": 0,
                "points_lost": 0,
            }

    # Beregn Elo kronologisk
    K = 32
    for m in chronological_matches:
        t1_players = [p.strip() for p in m["team1"].split("&")]
        t2_players = [p.strip() for p in m["team2"].split("&")]
        for p in t1_players + t2_players:
            ensure_player(p)

        t1_elo = sum(stats[p]["elo"] for p in t1_players) / len(t1_players)
        t2_elo = sum(stats[p]["elo"] for p in t2_players) / len(t2_players)

        ea = 1 / (1 + 10 ** ((t2_elo - t1_elo) / 400))
        eb = 1 - ea

        s1_wins = sum(1 for s1, s2 in m["sets"] if s1 > s2)
        s2_wins = sum(1 for s1, s2 in m["sets"] if s2 > s1)
        sa = 1.0 if s1_wins > s2_wins else 0.0
        sb = 1.0 - sa

        for p in t1_players:
            stats[p]["elo"] += K * (sa - ea)
        for p in t2_players:
            stats[p]["elo"] += K * (sb - eb)

    # Beregn kumulativ statistik filtreret efter type
    for m in matches:
        if filter_type != "all" and m["match_type"] != filter_type:
            continue

        t1_players = [p.strip() for p in m["team1"].split("&")]
        t2_players = [p.strip() for p in m["team2"].split("&")]

        s1_wins = sum(1 for s1, s2 in m["sets"] if s1 > s2)
        s2_wins = sum(1 for s1, s2 in m["sets"] if s2 > s1)

        t1_pts = sum(s[0] for s in m["sets"])
        t2_pts = sum(s[1] for s in m["sets"])

        for p in t1_players:
            stats[p]["matches_played"] += 1
            if s1_wins > s2_wins:
                stats[p]["matches_won"] += 1
            else:
                stats[p]["matches_lost"] += 1
            stats[p]["sets_won"] += s1_wins
            stats[p]["sets_lost"] += s2_wins
            stats[p]["points_won"] += t1_pts
            stats[p]["points_lost"] += t2_pts

        for p in t2_players:
            stats[p]["matches_played"] += 1
            if s2_wins > s1_wins:
                stats[p]["matches_won"] += 1
            else:
                stats[p]["matches_lost"] += 1
            stats[p]["sets_won"] += s2_wins
            stats[p]["sets_lost"] += s1_wins
            stats[p]["points_won"] += t2_pts
            stats[p]["points_lost"] += t1_pts

    leaderboard = list(stats.values())
    for item in leaderboard:
        item["elo"] = round(item["elo"], 1)
        item["set_diff"] = item["sets_won"] - item["sets_lost"]
        item["point_diff"] = item["points_won"] - item["points_lost"]
    leaderboard.sort(key=lambda x: (x["elo"], x["set_diff"], x["point_diff"]), reverse=True)

    # Højdepunkter & Rekorder
    highlights = {
        "daily_form": None,
        "blowout": None,
        "thriller": None,
        "marathon": None
    }

    if matches:
        # 1. Dagens form (seneste dato)
        latest_date = max(m["match_date"] for m in matches)
        day_points: Dict[str, int] = {}
        for m in matches:
            if m["match_date"] == latest_date:
                t1 = [p.strip() for p in m["team1"].split("&")]
                t2 = [p.strip() for p in m["team2"].split("&")]
                diff = sum(s[0] - s[1] for s in m["sets"])
                for p in t1:
                    day_points[p] = day_points.get(p, 0) + diff
                for p in t2:
                    day_points[p] = day_points.get(p, 0) - diff
        if day_points:
            best_p = max(day_points, key=day_points.get)
            highlights["daily_form"] = f"{PLAYERS.get(best_p, best_p)} ({latest_date}, diff: {day_points[best_p]:+d})"

        # 2. Største Nedsabling, 3. Tætteste Gysersæt, 4. Maraton
        max_diff = -1
        tightest_score = -1
        max_total_points = -1

        for m in matches:
            match_pts = sum(s[0] + s[1] for s in m["sets"])
            if match_pts > max_total_points:
                max_total_points = match_pts
                highlights["marathon"] = f"{m['team1']} mod {m['team2']} ({match_pts} point i alt, {m['match_date']})"

            for s_idx, (s1, s2) in enumerate(m["sets"], start=1):
                diff = abs(s1 - s2)
                if diff > max_diff:
                    max_diff = diff
                    highlights["blowout"] = f"{max(s1, s2)}-{min(s1, s2)} (Sæt {s_idx}, {m['team1']} vs {m['team2']}, {m['match_date']})"

                # Gysersæt: Tæt margin med flest point (f.eks. forlængelser til 30-29)
                if diff <= 2 and (s1 >= 20 or s2 >= 20):
                    total_set = s1 + s2
                    if total_set > tightest_score:
                        tightest_score = total_set
                        highlights["thriller"] = f"{s1}-{s2} (Sæt {s_idx}, {m['team1']} vs {m['team2']}, {m['match_date']})"

    return leaderboard, highlights

def get_head_to_head_stats(p1: str, p2: str) -> Dict[str, Any]:
    matches = get_all_matches()
    h2h_matches = []

    p1_match_wins = 0
    p2_match_wins = 0
    p1_set_wins = 0
    p2_set_wins = 0
    p1_points = 0
    p2_points = 0

    for m in matches:
        if m["match_type"] != "single":
            continue

        is_p1_t1 = m["team1"] == p1 and m["team2"] == p2
        is_p1_t2 = m["team1"] == p2 and m["team2"] == p1

        if not (is_p1_t1 or is_p1_t2):
            continue

        s1_w = 0
        s2_w = 0
        match_sets_normalized = []

        for s1, s2 in m["sets"]:
            score_p1 = s1 if is_p1_t1 else s2
            score_p2 = s2 if is_p1_t1 else s1

            p1_points += score_p1
            p2_points += score_p2

            if score_p1 > score_p2:
                p1_set_wins += 1
                s1_w += 1
            elif score_p2 > score_p1:
                p2_set_wins += 1
                s2_w += 1

            match_sets_normalized.append((score_p1, score_p2))

        if s1_w > s2_w:
            p1_match_wins += 1
            winner = p1
        else:
            p2_match_wins += 1
            winner = p2

        h2h_matches.append({
            "id": m["id"],
            "date": m["match_date"],
            "score": f"{s1_w}-{s2_w}",
            "winner": winner,
            "sets": match_sets_normalized
        })

    return {
        "p1": p1,
        "p2": p2,
        "p1_name": PLAYERS.get(p1, p1),
        "p2_name": PLAYERS.get(p2, p2),
        "total_matches": len(h2h_matches),
        "p1_match_wins": p1_match_wins,
        "p2_match_wins": p2_match_wins,
        "p1_set_wins": p1_set_wins,
        "p2_set_wins": p2_set_wins,
        "p1_points": p1_points,
        "p2_points": p2_points,
        "matches": h2h_matches
    }

def export_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "match_date", "match_type", "team1", "team2", "target_sets", "scores"])
    for m in get_all_matches():
        scores_str = ";".join(f"{s[0]}-{s[1]}" for s in m["sets"])
        writer.writerow([m["id"], m["match_date"], m["match_type"], m["team1"], m["team2"], m["target_sets"], scores_str])
    return output.getvalue()

def import_csv(csv_text: str) -> None:
    reader = csv.DictReader(io.StringIO(csv_text))
    with get_conn() as conn:
        conn.execute("DELETE FROM sets")
        conn.execute("DELETE FROM matches")
        for row in reader:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO matches (id, match_date, match_type, team1, team2, target_sets) VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["match_date"], row["match_type"], row["team1"], row["team2"], row["target_sets"])
            )
            m_id = row["id"]
            for idx, pair in enumerate(row["scores"].split(";"), start=1):
                if pair:
                    s1, s2 = pair.split("-")
                    cursor.execute(
                        "INSERT INTO sets (match_id, set_number, score1, score2) VALUES (?, ?, ?, ?)",
                        (m_id, idx, int(s1), int(s2))
                    )
