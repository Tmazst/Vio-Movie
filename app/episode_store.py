import json
import sqlite3
from pathlib import Path
from typing import Any

from app.character_store import DATABASE_PATH

EPISODE_STATUSES = [
    "Planning", "Script Ready", "Storyboarding", "Generating", "Editing", "Complete"
]
SCENE_STATUSES = ["Planned", "Ready", "Generated", "Edited"]


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_number INTEGER NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Planning',
            script_path TEXT NOT NULL DEFAULT '',
            character_ids TEXT NOT NULL DEFAULT '[]',
            scenes TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    return connection


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key, default in (("character_ids", []), ("scenes", [])):
        try:
            item[key] = json.loads(item.get(key) or "[]")
        except (TypeError, json.JSONDecodeError):
            item[key] = default
    return item


def list_episodes() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM episodes ORDER BY episode_number, id"
        ).fetchall()
    return [_decode(row) for row in rows]


def get_episode(episode_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM episodes WHERE id = ?", (episode_id,)
        ).fetchone()
    return _decode(row) if row else None


def _clean_payload(data: dict[str, Any]) -> dict[str, Any]:
    try:
        number = int(data.get("episode_number", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Episode number must be a positive whole number.") from error
    if number < 1 or number > 9999:
        raise ValueError("Episode number must be between 1 and 9999.")

    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("Episode title is required.")
    if len(title) > 200:
        raise ValueError("Episode title must be 200 characters or fewer.")

    summary = str(data.get("summary", "")).strip()
    if len(summary) > 20000:
        raise ValueError("Episode summary must be 20,000 characters or fewer.")

    status = str(data.get("status", "Planning")).strip()
    if status not in EPISODE_STATUSES:
        raise ValueError("Choose a valid episode production status.")

    script_path = str(data.get("script_path", "")).strip()
    character_ids = data.get("character_ids", [])
    scenes = data.get("scenes", [])
    if not isinstance(character_ids, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in character_ids
    ):
        raise ValueError("Assigned characters must be a list of character IDs.")
    if len(set(character_ids)) != len(character_ids) or len(character_ids) > 100:
        raise ValueError("Choose each character only once.")
    if not isinstance(scenes, list) or len(scenes) > 300:
        raise ValueError("Scenes must be a list with no more than 300 scenes.")

    cleaned_scenes = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError("Each scene must contain scene details.")
        try:
            scene_number = int(scene.get("scene_number", index))
            duration = int(scene.get("duration_seconds", 0) or 0)
        except (TypeError, ValueError) as error:
            raise ValueError("Scene numbers and durations must be whole numbers.") from error
        if scene_number < 1 or scene_number > 9999:
            raise ValueError("Scene numbers must be positive.")
        if duration < 0 or duration > 86400:
            raise ValueError("Scene duration must be between 0 and 86400 seconds.")
        scene_title = str(scene.get("title", "")).strip()
        scene_status = str(scene.get("status", "Planned")).strip()
        scene_characters = scene.get("character_ids", [])
        if scene_status not in SCENE_STATUSES:
            raise ValueError(f"Choose a valid status for Scene {scene_number}.")
        if not isinstance(scene_characters, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in scene_characters
        ):
            raise ValueError(f"Scene {scene_number} characters must be selected from the Character Bible.")
        if len(set(scene_characters)) != len(scene_characters):
            raise ValueError(f"Scene {scene_number} contains a duplicate character.")
        cleaned_scenes.append({
            "scene_number": scene_number,
            "title": scene_title,
            "location": str(scene.get("location", "")).strip()[:500],
            "time_of_day": str(scene.get("time_of_day", "")).strip()[:100],
            "character_ids": list(dict.fromkeys(scene_characters)),
            "action": str(scene.get("action", "")).strip()[:12000],
            "dialogue": str(scene.get("dialogue", "")).strip()[:20000],
            "props": str(scene.get("props", "")).strip()[:4000],
            "lighting": str(scene.get("lighting", "")).strip()[:2000],
            "duration_seconds": duration,
            "status": scene_status,
        })
    if len({scene["scene_number"] for scene in cleaned_scenes}) != len(cleaned_scenes):
        raise ValueError("Scene numbers must be unique within an episode.")

    with connect() as connection:
        known_ids = {
            row["id"] for row in connection.execute("SELECT id FROM characters").fetchall()
        }
    all_ids = set(character_ids)
    for scene in cleaned_scenes:
        all_ids.update(scene["character_ids"])
    if not all_ids.issubset(known_ids):
        raise ValueError("One or more selected characters no longer exist in the Character Bible.")

    return {
        "episode_number": number,
        "title": title,
        "summary": summary,
        "status": status,
        "script_path": script_path,
        "character_ids": json.dumps(list(dict.fromkeys(character_ids))),
        "scenes": json.dumps(cleaned_scenes, ensure_ascii=False),
    }


def save_episode(data: dict[str, Any], episode_id: int | None = None) -> dict[str, Any]:
    values = _clean_payload(data)
    with connect() as connection:
        try:
            if episode_id is None:
                cursor = connection.execute(
                    """INSERT INTO episodes
                    (episode_number, title, summary, status, script_path, character_ids, scenes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    tuple(values[key] for key in (
                        "episode_number", "title", "summary", "status", "script_path",
                        "character_ids", "scenes"
                    )),
                )
                episode_id = cursor.lastrowid
            else:
                cursor = connection.execute(
                    """UPDATE episodes SET episode_number=?, title=?, summary=?, status=?,
                    script_path=?, character_ids=?, scenes=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?""",
                    tuple(values[key] for key in (
                        "episode_number", "title", "summary", "status", "script_path",
                        "character_ids", "scenes"
                    )) + (episode_id,),
                )
                if cursor.rowcount == 0:
                    raise LookupError("Episode not found.")
        except sqlite3.IntegrityError as error:
            raise ValueError("That episode number is already in use. Each episode number must be unique.") from error
    result = get_episode(int(episode_id))
    if result is None:
        raise RuntimeError("The saved episode could not be loaded.")
    return result


def delete_episode(episode_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
        return cursor.rowcount > 0
