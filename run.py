from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from app.character_store import delete_character, get_character, list_characters, save_character
from app.episode_store import delete_episode, get_episode, list_episodes, save_episode
from app.shot_store import generate_shots, list_shots, save_shots
from app.scanner import IMAGE_EXTENSIONS, scan_project

app = Flask(__name__, template_folder="app/templates")
DEFAULT_PROJECT_PATH = r"E:\Inkaka The Guru"


def get_project_root() -> Path:
    root = Path(request.args.get("path", DEFAULT_PROJECT_PATH)).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Project folder does not exist or is not a directory: {root}")
    return root


def validate_reference_images(images: list[str]) -> None:
    """Prevent saving reference paths that point outside the active project."""
    root = get_project_root()
    for relative_path in images:
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("Reference images must be inside the project folder.") from error
        if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Reference image was not found or is not an image: {relative_path}")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/library")
def library():
    return render_template("library.html")


@app.get("/characters")
def characters_page():
    return render_template("characters.html")


@app.get("/episodes")
def episodes_page():
    return render_template("episodes.html")


@app.get("/shots")
def shots_page():
    return render_template("shots.html")


def validate_script_path(relative_path: str) -> None:
    """Allow linking only to an existing file inside the production folder."""
    if not relative_path:
        return
    root = get_project_root()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("The linked script must be inside the production folder.") from error
    if not candidate.is_file():
        raise ValueError(f"The linked script file was not found: {relative_path}")


@app.get("/api/episodes")
def episodes_list():
    return jsonify({"episodes": list_episodes()})


@app.post("/api/episodes")
def episodes_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send episode details as JSON."}), 400
    try:
        validate_script_path(str(data.get("script_path", "")).strip())
        episode = save_episode(data)
        return jsonify({"episode": episode}), 201
    except (OSError, ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.put("/api/episodes/<int:episode_id>")
def episodes_update(episode_id: int):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send episode details as JSON."}), 400
    try:
        validate_script_path(str(data.get("script_path", "")).strip())
        episode = save_episode(data, episode_id)
        return jsonify({"episode": episode})
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except (OSError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@app.delete("/api/episodes/<int:episode_id>")
def episodes_delete(episode_id: int):
    if not delete_episode(episode_id):
        return jsonify({"error": "Episode not found."}), 404
    return jsonify({"deleted": True})


@app.get("/api/episodes/<int:episode_id>/shots")
def episode_shots_list(episode_id: int):
    if get_episode(episode_id) is None:
        return jsonify({"error": "Episode not found."}), 404
    return jsonify({"shots": list_shots(episode_id)})


@app.post("/api/episodes/<int:episode_id>/shots/generate")
def episode_shots_generate(episode_id: int):
    data = request.get_json(silent=True) or {}
    try:
        clip_seconds = int(data.get("clip_seconds", 5))
        shots = generate_shots(episode_id, clip_seconds)
        return jsonify({"shots": shots})
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except (OSError, TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@app.put("/api/episodes/<int:episode_id>/shots")
def episode_shots_update(episode_id: int):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        return jsonify({"error": "Send the shot list as a JSON array named shots."}), 400
    try:
        for shot in data["shots"]:
            if not isinstance(shot, dict):
                raise ValueError("Each shot must contain shot details.")
            images = shot.get("reference_images", [])
            if not isinstance(images, list):
                raise ValueError("Shot reference images must be a list.")
            validate_reference_images(images)
        shots = save_shots(episode_id, data["shots"])
        return jsonify({"shots": shots})
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except (OSError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@app.get("/api/project/scan")
def project_scan():
    try:
        return jsonify(scan_project(str(get_project_root())))
    except (OSError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@app.get("/api/project/assets")
def project_assets():
    try:
        result = scan_project(str(get_project_root()))
    except (OSError, ValueError) as error:
        return jsonify({"error": str(error)}), 400

    category = request.args.get("category", "").strip().lower()
    files = result["files"]
    if category and category != "all":
        files = [item for item in files if item["category"] == category]
    return jsonify({
        "project_root": result["project_root"],
        "total_files": len(files),
        "categories": result["categories"],
        "assets": files,
        "errors": result["errors"],
    })


@app.get("/api/project/preview")
def project_preview():
    relative_path = request.args.get("file", "")
    if not relative_path:
        abort(400, description="Missing file path.")
    try:
        root = get_project_root()
        target = (root / relative_path).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        abort(404)
    if not target.is_file() or target.suffix.lower() not in IMAGE_EXTENSIONS:
        abort(404)
    return send_file(target, conditional=True)


@app.get("/api/characters")
def characters_list():
    return jsonify({"characters": list_characters()})


@app.post("/api/characters")
def characters_create():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send character details as JSON."}), 400
    try:
        images = data.get("reference_images", [])
        if not isinstance(images, list):
            raise ValueError("Reference images must be a list.")
        validate_reference_images(images)
        character = save_character(data)
        return jsonify({"character": character}), 201
    except (OSError, ValueError, LookupError) as error:
        return jsonify({"error": str(error)}), 400


@app.put("/api/characters/<int:character_id>")
def characters_update(character_id: int):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send character details as JSON."}), 400
    try:
        images = data.get("reference_images", [])
        if not isinstance(images, list):
            raise ValueError("Reference images must be a list.")
        validate_reference_images(images)
        character = save_character(data, character_id)
        return jsonify({"character": character})
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except (OSError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@app.delete("/api/characters/<int:character_id>")
def characters_delete(character_id: int):
    if not delete_character(character_id):
        return jsonify({"error": "Character not found."}), 404
    return jsonify({"deleted": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
