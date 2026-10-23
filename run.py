from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from app.scanner import IMAGE_EXTENSIONS, scan_project

# Templates currently live in app/templates rather than a top-level templates folder.
app = Flask(__name__, template_folder="app/templates")

DEFAULT_PROJECT_PATH = r"E:\\Inkaka The Guru"


def get_project_root() -> Path:
    """Return the configured production folder, resolved to an absolute path."""
    root = Path(request.args.get("path", DEFAULT_PROJECT_PATH)).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Project folder does not exist or is not a directory: {root}")
    return root


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/library")
def library():
    return render_template("library.html")


@app.get("/api/project/scan")
def project_scan():
    try:
        return jsonify(scan_project(str(get_project_root())))
    except (OSError, ValueError) as error:
        return jsonify({"error": str(error)}), 400


@app.get("/api/project/assets")
def project_assets():
    """Return metadata for the production library, optionally filtered by category."""
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
    """Serve an image preview only when its resolved path remains inside the project."""
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
