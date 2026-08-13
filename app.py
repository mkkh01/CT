from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route("/")
@app.route("/<path:p>")
def hello(p=""):
    return jsonify({
        "message": "Minimal App is running",
        "path": p,
        "env_keys": list(os.environ.keys())
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
