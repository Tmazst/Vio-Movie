import json
import sqlite3
from pathlib import Path
from typing import Any

DATABASE_PATH = Path(__file__).resolve().parent.parent / "instance" / "vio_movie.db"


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            locked_description TEXT NOT NULL DEFAULT '',
            outfit TEXT NOT NULL DEFAULT '',
            voice_id TEXT NOT NULL DEFAULT '',
            continuity_notes TEXT NOT NULL DEFAULT '',
            reference_images TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    return connection


def list_characters() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM characters ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [to_dict(row) for row in rows]


def get_character(character_id: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
    return to_dict(row) if row else None


def save_character(data: dict[str, Any], character_id: int | None = None) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("Character name is required.")
    if len(name) > 100:
        raise ValueError("Character name must be 100 characters or fewer.")

    fields = {
        "locked_description": str(data.get("locked_description", "")).strip(),
        "outfit": str(data.get("outfit", "")).strip(),
        "voice_id": str(data.get("voice_id", "")).strip(),
        "continuity_notes": str(data.get("continuity_notes", "")).strip(),
    }
    if any(len(value) > 12000 for value in fields.values()):
        raise ValueError("Each character field must be 12,000 characters or fewer.")

    images = data.get("reference_images", [])
    if not isinstance(images, list) or any(not isinstance(item, str) for item in images):
        raise ValueError("Reference images must be a list of file paths.")
    images = list(dict.fromkeys(item.strip() for item in images if item.strip()))
    if len(images) > 30:
        raise ValueError("A character can have at most 30 reference images.")
    images_json = json.dumps(images, ensure_ascii=False)

    with connect() as connection:
        try:
            if character_id is None:
                cursor = connection.execute(
                    """INSERT INTO characters
                    (name, locked_description, outfit, voice_id, continuity_notes, reference_images)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, fields["locked_description"], fields["outfit"], fields["voice_id"],
                     fields["continuity_notes"], images_json),
                )
                character_id = cursor.lastrowid
            else:
                cursor = connection.execute(
                    """UPDATE characters SET name=?, locked_description=?, outfit=?, voice_id=?,
                    continuity_notes=?, reference_images=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (name, fields["locked_description"], fields["outfit"], fields["voice_id"],
                     fields["continuity_notes"], images_json, character_id),
                )
                if cursor.rowcount == 0:
                    raise LookupError("Character not found.")
        except sqlite3.IntegrityError as error:
            raise ValueError("A character with that name already exists.") from error

    result = get_character(int(character_id))
    if result is None:
        raise RuntimeError("The saved character could not be loaded.")
    return result


def delete_character(character_id: int) -> bool:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM characters WHERE id = ?", (character_id,))
        return cursor.rowcount > 0


def to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    try:
        result["reference_images"] = json.loads(result.get("reference_images") or "[]")
    except (TypeError, json.JSONDecodeError):
        result["reference_images"] = []
    return result
