from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
@app.route("/ping")
@app.route("/healthz")
def hello():
    return "Hello, the server is alive!", 200

@app.route("/dashboard/api/overview")
def overview():
    return jsonify({
        "overview": {
            "service": "CT Binance Spot Live Recommendations",
            "runtime_started": True,
            "websocket_connected": True,
            "live_data_available": True,
            "coins": [],
            "total_capital": 0.0,
            "realized_pnl_today": 0.0,
            "open_positions_count": 0,
            "cycles": 0,
            "signals": 0,
            "win_rate": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "market_status": {}
        },
        "open_positions": [],
        "recent_signals": [],
        "recent_positions": [],
        "events": [],
        "logs": []
    })
