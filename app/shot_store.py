import json
import sqlite3
from typing import Any

from app.character_store import DATABASE_PATH, list_characters
from app.episode_store import get_episode

SHOT_STATUSES = ["Planned", "Prompt Ready", "Generated", "Approved"]


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS episode_shots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id INTEGER NOT NULL UNIQUE,
            shots TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    return connection


def list_shots(episode_id: int) -> list[dict[str, Any]]:
    with connect() as connection:
        row = connection.execute(
            "SELECT shots FROM episode_shots WHERE episode_id = ?", (episode_id,)
        ).fetchone()
    if not row:
        return []
    try:
        value = json.loads(row["shots"] or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def save_shots(episode_id: int, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(shots, list) or len(shots) > 2000:
        raise ValueError("Shots must be a list containing no more than 2,000 items.")
    if get_episode(episode_id) is None:
        raise LookupError("Episode not found.")
    characters = {item["id"]: item for item in list_characters()}
    cleaned = []
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise ValueError("Each shot must contain shot details.")
        try:
            duration = int(shot.get("duration_seconds", 5))
            scene_number = int(shot.get("scene_number", 1))
        except (TypeError, ValueError) as error:
            raise ValueError("Shot scene numbers and durations must be whole numbers.") from error
        if duration < 1 or duration > 60:
            raise ValueError("Shot duration must be between 1 and 60 seconds.")
        if scene_number < 1:
            raise ValueError("Shot scene numbers must be positive.")
        ids = shot.get("character_ids", [])
        if not isinstance(ids, list) or any(type(value) is not int or value not in characters for value in ids):
            raise ValueError("A shot contains an invalid Character Bible ID.")
        if len(set(ids)) != len(ids) or len(ids) > 2:
            raise ValueError("Each shot can include at most two different characters.")
        status = str(shot.get("status") or "Planned").strip()
        if status not in SHOT_STATUSES:
            raise ValueError("Choose a valid shot production status.")
        cleaned.append({
            "shot_number": index,
            "scene_number": scene_number,
            "title": str(shot.get("title", "")).strip()[:300],
            "location": str(shot.get("location", "")).strip()[:500],
            "time_of_day": str(shot.get("time_of_day", "")).strip()[:100],
            "character_ids": ids,
            "character_names": [characters[value]["name"] for value in ids],
            "action": str(shot.get("action", "")).strip()[:12000],
            "dialogue": str(shot.get("dialogue", "")).strip()[:12000],
            "props": str(shot.get("props", "")).strip()[:4000],
            "lighting": str(shot.get("lighting", "")).strip()[:2000],
            "duration_seconds": duration,
            "status": status,
            "prompt": str(shot.get("prompt", "")).strip()[:20000],
            "negative_prompt": str(shot.get("negative_prompt") or "cartoon, anime, CGI, plastic skin, deformed face, extra fingers, changing clothes, inconsistent identity, blended people").strip()[:4000],
            "reference_images": [path for path in shot.get("reference_images", []) if isinstance(path, str)][:10] if isinstance(shot.get("reference_images", []), list) else [],
        })
    payload = json.dumps(cleaned, ensure_ascii=False)
    with connect() as connection:
        connection.execute("""
            INSERT INTO episode_shots (episode_id, shots) VALUES (?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET shots=excluded.shots, updated_at=CURRENT_TIMESTAMP
        """, (episode_id, payload))
    return cleaned


def generate_shots(episode_id: int, clip_seconds: int = 5) -> list[dict[str, Any]]:
    if clip_seconds not in (5, 6, 8, 10):
        raise ValueError("Choose a clip duration of 5, 6, 8, or 10 seconds.")
    episode = get_episode(episode_id)
    if episode is None:
        raise LookupError("Episode not found.")
    characters = {item["id"]: item for item in list_characters()}
    episode_cast = episode.get("character_ids", [])
    generated = []
    for scene in episode.get("scenes", []):
        ids = scene.get("character_ids") or episode_cast
        # Never place more than two characters in a generated shot.
        groups = [ids[i:i + 2] for i in range(0, len(ids), 2)] or [[]]
        duration = int(scene.get("duration_seconds") or clip_seconds)
        segment_count = max(1, (duration + clip_seconds - 1) // clip_seconds)
        for segment in range(segment_count):
            for group_index, group in enumerate(groups):
                length = min(clip_seconds, duration - segment * clip_seconds) if duration > 0 else clip_seconds
                length = max(1, length)
                descriptions = []
                refs = []
                for character_id in group:
                    character = characters.get(character_id)
                    if not character:
                        continue
                    identity = character.get("locked_description", "").strip()
                    outfit = character.get("outfit", "").strip()
                    descriptions.append(character["name"] + ": " + identity + (", wearing " + outfit if outfit else ""))
                    refs.extend(character.get("reference_images", []))
                location = scene.get("location") or "location not specified"
                action = scene.get("action") or scene.get("title") or "Natural character movement in the scene"
                if segment_count > 1:
                    action = action + f" (continuous action, clip {segment + 1} of {segment_count})"
                if len(groups) > 1:
                    action = action + f" (coverage group {group_index + 1} of {len(groups)}; keep only the named characters in this shot)"
                prompt_parts = [
                    "Realistic live-action cinematic shot.",
                    "Character identity and outfit locks: " + "; ".join(descriptions) if descriptions else "No defined character reference; use a realistic cinematic environment shot.",
                    "Location: " + location + (", " + str(scene.get("time_of_day")) if scene.get("time_of_day") else "") + ".",
                    "Action: " + action + ".",
                    "Dialogue: " + str(scene.get("dialogue") or "No spoken dialogue specified") + ".",
                    "Props and continuity: " + str(scene.get("props") or "Maintain scene continuity") + ".",
                    "Lighting and atmosphere: " + str(scene.get("lighting") or "Natural cinematic lighting") + ".",
                    f"Natural skin texture, realistic anatomy, cinematic 35mm look, subtle camera movement, {length} seconds.",
                    "Use the same character reference images and do not redesign faces, hair, or clothing.",
                ]
                generated.append({
                    "scene_number": int(scene.get("scene_number", 1)),
                    "title": str(scene.get("title") or f"Scene {scene.get('scene_number', 1)}"),
                    "location": location,
                    "time_of_day": str(scene.get("time_of_day") or ""),
                    "character_ids": group,
                    "action": action,
                    "dialogue": str(scene.get("dialogue") or ""),
                    "props": str(scene.get("props") or ""),
                    "lighting": str(scene.get("lighting") or ""),
                    "duration_seconds": length,
                    "status": "Prompt Ready",
                    "prompt": " ".join(prompt_parts),
                    "negative_prompt": "cartoon, anime, CGI, plastic skin, deformed face, extra fingers, changing clothes, inconsistent identity, blended people, duplicate characters, text artifacts",
                    "reference_images": list(dict.fromkeys(refs)),
                })
    return save_shots(episode_id, generated)
