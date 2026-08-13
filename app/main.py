from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/ping")
def ping():
    return "pong", 200

@app.route("/dashboard/api/overview")
def overview():
    return jsonify({"status": "minimal_success", "message": "This is a direct JSON response from Flask."}), 200

if __name__ == "__main__":
    app.run()
