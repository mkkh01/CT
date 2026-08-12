from flask import Flask

app = Flask(__name__)

@app.route("/")
@app.route("/ping")
@app.route("/healthz")
def hello():
    return "Hello, the server is alive!", 200

if __name__ == "__main__":
    app.run()
