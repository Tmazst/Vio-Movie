from flask import Flask, jsonify, render_template, request

from app.scanner import scan_project

app = Flask(__name__)

DEFAULT_PROJECT_PATH = r"E:\Inkaka The Guru"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/project/scan")
def project_scan():
    project_path = request.args.get(
        "path",
        DEFAULT_PROJECT_PATH,
    )

    try:
        result = scan_project(project_path)
        return jsonify(result)

    except (OSError, ValueError) as error:
        return jsonify({
            "error": str(error),
        }), 400


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )