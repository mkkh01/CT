from app.main import app
import os

if __name__ == "__main__":
    print("Starting test app on port 5000...")
    app.run(host="0.0.0.0", port=5000)
