import logging
import os
import time

import requests
from flask import Flask, g, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("order_service")
logging.getLogger("werkzeug").setLevel(logging.WARNING)

INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://127.0.0.1:8001")
TIMEOUT_SECONDS = 2

# in-memory orders, owned only by this service
orders = {}
next_id = 1


def publish_order_created(order):
    # stub: a real Notification Service would consume this event later
    log.info("event=OrderCreated order_id=%s item_id=%s quantity=%s",
             order["order_id"], order["item_id"], order["quantity"])


@app.before_request
def start_timer():
    g.start = time.time()


@app.after_request
def log_request(response):
    latency_ms = round((time.time() - g.start) * 1000, 2)
    log.info("service=order endpoint=%s %s status=%s latency_ms=%s",
             request.method, request.path, response.status_code, latency_ms)
    return response


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "order"}), 200


@app.post("/orders")
def create_order():
    global next_id
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be JSON"}), 400

    item_id = data.get("item_id")
    quantity = data.get("quantity")
    if not isinstance(item_id, str) or not item_id.strip():
        return jsonify({"error": "item_id is required"}), 400
    # bool is a subclass of int, so reject it on purpose
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return jsonify({"error": "quantity must be a positive integer"}), 400

    try:
        resp = requests.get(f"{INVENTORY_URL}/inventory/{item_id}",
                            params={"quantity": quantity}, timeout=TIMEOUT_SECONDS)
    # could not connect at all (on Windows a closed port can show up as a connect timeout)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
        log.error("inventory service unavailable item_id=%s", item_id)
        return jsonify({"error": "inventory service unavailable"}), 503
    # connected, but inventory took too long to answer
    except requests.exceptions.ReadTimeout:
        log.error("inventory call timed out item_id=%s", item_id)
        return jsonify({"error": "inventory service timed out"}), 504
    except requests.exceptions.RequestException as e:
        log.error("inventory call failed item_id=%s error=%s", item_id, e)
        return jsonify({"error": "inventory service error"}), 502

    if resp.status_code == 404:
        return jsonify({"error": "item not found", "item_id": item_id}), 404
    if resp.status_code != 200:
        log.error("unexpected inventory response status=%s", resp.status_code)
        return jsonify({"error": "inventory service error"}), 502

    info = resp.json()
    if not info.get("available"):
        return jsonify({
            "error": "not enough stock",
            "item_id": item_id,
            "requested": quantity,
            "in_stock": info.get("in_stock"),
        }), 409

    order_id = f"o{next_id}"
    next_id += 1
    order = {"order_id": order_id, "item_id": item_id, "quantity": quantity, "status": "created"}
    orders[order_id] = order
    publish_order_created(order)
    return jsonify(order), 201


@app.get("/orders/<order_id>")
def get_order(order_id):
    order = orders.get(order_id)
    if order is None:
        return jsonify({"error": "order not found", "order_id": order_id}), 404
    return jsonify(order), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
