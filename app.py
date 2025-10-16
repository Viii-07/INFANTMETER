import asyncio
import cv2
import numpy as np

import threading
from bleak import BleakClient, BleakScanner
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

# BLE UUIDs
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CHARACTERISTIC_UUID = "12345678-1234-5678-1234-56789abcdef1"

# Shared data
ble_loop = asyncio.new_event_loop()
weight_data = {"value": None, "connected": False}
height_data = {"value": None}  # type: dict[str, float | None]

# ---------------- HTML (Front-end) ----------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"UTF-8\">
<title>Infant BMI Calculator</title>
<style>
    body { font-family: 'Segoe UI', sans-serif; text-align: center; padding: 40px; background: #f8f9fa; }
    h2 { color: #2a2a2a; }
    .container { background: white; width: 400px; margin: auto; padding: 20px; border-radius: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    input { padding: 10px; width: 90%; border-radius: 6px; border: 1px solid #ccc; margin: 8px 0; }
    button { padding: 10px 20px; border: none; border-radius: 6px; margin-top: 10px; cursor: pointer; }
    #connectBtn { background: #007bff; color: white; }
    #measureBtn { background: #17a2b8; color: white; }
    #calcBtn { background: #28a745; color: white; }
    #status { font-size: 14px; color: gray; margin-bottom: 10px; }
    .value { font-weight: bold; font-size: 18px; }
</style>
</head>
<body>
<div class=\"container\">
    <h2>Infant BMI Calculator</h2>
    <p id=\"status\">Status: Not Connected</p>
    <p>Height (cm): <span id=\"height\" class=\"value\">--</span></p>
    <p>Weight (kg): <span id=\"weight\" class=\"value\">--</span></p>
    <p>BMI: <span id=\"bmi\" class=\"value\">--</span></p>
    <button id=\"connectBtn\" onclick=\"connectBLE()\">Connect ESP32</button>
    <button id=\"measureBtn\" onclick=\"measureHeight()\">Measure Height</button>
    <button id=\"calcBtn\" onclick=\"calculateBMI()\">Calculate BMI</button>
</div>
<script>
let connected = false;
function updateStatus() {
    fetch('/status').then(res => res.json()).then(data => {
        document.getElementById('status').innerText = 'Status: ' + (data.connected ? 'Connected' : 'Not Connected');
    });
}
async function connectBLE() {
    const res = await fetch('/connect');
    const data = await res.json();
    alert(data.message);
    updateStatus();
    if (data.connected) {
        connected = true;
        pollWeight();
    }
}
async function pollWeight() {
    setInterval(async () => {
        const res = await fetch('/get_weight');
        const data = await res.json();
        if (data.weight) {
            document.getElementById('weight').innerText = data.weight;
        }
    }, 2000);
}
async function measureHeight() {
    const res = await fetch('/measure_height');
    const data = await res.json();
    if (data.height) {
        document.getElementById('height').innerText = data.height;
    }
}
async function pollHeight() {
    setInterval(async () => {
        const res = await fetch('/get_height');
        const data = await res.json();
        if (data.height) {
            document.getElementById('height').innerText = data.height;
        }
    }, 2000);
}
async function calculateBMI() {
    const height = document.getElementById('height').innerText;
    const weight = document.getElementById('weight').innerText;
    const res = await fetch('/calculate_bmi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ height, weight })
    });
    const data = await res.json();
    if (data.bmi) {
        document.getElementById('bmi').innerText = data.bmi;
    } else if (data.error) {
        alert(data.error);
    }
}
updateStatus();
pollHeight();
</script>
</body>
</html>
"""

# ---------------- Flask Routes ----------------

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/connect')
def connect_ble():
    if weight_data["connected"]:
        return jsonify({"message": "Already connected to ESP32", "connected": True})
    threading.Thread(target=start_ble, daemon=True).start()
    return jsonify({"message": "Attempting to connect to ESP32...", "connected": False})

def start_ble():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_ble())

async def run_ble():
    devices = await BleakScanner.discover()
    esp32_device = None
    for d in devices:
        if d.name and "ESP32Scale" in d.name:
            esp32_device = d
            break
    if not esp32_device:
        print("ESP32 not found.")
        weight_data["connected"] = False
        return

    async with BleakClient(esp32_device) as client:
        weight_data["connected"] = True
        print("Connected to ESP32")

        def callback(sender, data):
            weight = data.decode('utf-8').strip()
            weight_data["value"] = weight
            print(f"Received weight: {weight} kg")

        await client.start_notify(CHARACTERISTIC_UUID, callback)

        while True:
            await asyncio.sleep(1)

@app.route('/get_weight')
def get_weight():
    return jsonify({"weight": weight_data["value"]})

@app.route('/status')
def status():
    return jsonify({"connected": weight_data["connected"]})

@app.route('/get_height')
def get_height():
    return jsonify({"height": height_data["value"]})

@app.route('/measure_height')
def measure_height():
    # OpenCV logic to measure height using a calibration marker
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return jsonify({"error": "Camera error"})
    # Dummy calibration: Assume marker is 10cm and 100px tall
    marker_cm = 10.0
    marker_px = 100.0
    # Detect marker and infant height (replace with real detection)
    # For now, simulate with fixed values
    infant_px = 300.0
    cm_per_px = marker_cm / marker_px
    height_cm = infant_px * cm_per_px
    height_data["value"] = round(height_cm, 2)
    return jsonify({"height": height_data["value"]})

@app.route('/calculate_bmi', methods=['POST'])
def calculate_bmi():
    try:
        data = request.get_json()
        height = float(data.get("height", 0))
        weight = float(data.get("weight", 0))
        if height <= 0 or weight <= 0:
            raise ValueError("Invalid input")
        bmi = weight / ((height / 100) ** 2)
        return jsonify({"bmi": round(bmi, 2)})
    except Exception:
        return jsonify({"error": "Invalid input or missing weight data"})

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Use Render's port if available
    app.run(host="0.0.0.0", port=port, debug=True)
