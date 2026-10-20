import logging
import time

from flask import Flask, g, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inventory_service")
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# in-memory stock, owned only by this service
stock = {"apple": 10, "banana": 5, "laptop": 2}


@app.before_request
def start_timer():
    g.start = time.time()


@app.after_request
def log_request(response):
    latency_ms = round((time.time() - g.start) * 1000, 2)
    log.info("service=inventory endpoint=%s %s status=%s latency_ms=%s",
             request.method, request.path, response.status_code, latency_ms)
    return response


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "inventory"}), 200


@app.get("/inventory/<item_id>")
def check_inventory(item_id):
    if item_id not in stock:
        return jsonify({"error": "item not found", "item_id": item_id}), 404

    try:
        quantity = int(request.args.get("quantity", ""))
    except ValueError:
        return jsonify({"error": "quantity must be a positive integer"}), 400
    if quantity <= 0:
        return jsonify({"error": "quantity must be a positive integer"}), 400

    in_stock = stock[item_id]
    return jsonify({
        "item_id": item_id,
        "requested": quantity,
        "in_stock": in_stock,
        "available": in_stock >= quantity,
    }), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001)
