import time
import serial
from flask import Flask, render_template, request, jsonify
import config

app = Flask(__name__)

# Initialize Serial Connection
try:
    ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE, timeout=config.TIMEOUT)
    time.sleep(2)  # Wait for Arduino to reset
    print(f"Connected to Arduino on {config.SERIAL_PORT}")
except Exception as e:
    print(f"Could not connect to Serial: {e}")
    ser = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/send_command', methods=['POST'])
def send_command():
    if not ser:
        return jsonify({"status": "error", "message": "Serial not connected"}), 500
    
    data = request.json
    cmd_id = data.get('id')
    value = data.get('value')
    
    if cmd_id and value is not None:
        command = f"{cmd_id}:{value}\n"
        ser.write(command.encode())
        print(f"Sent: {command.strip()}")
        return jsonify({"status": "success", "command": command.strip()})
    
    return jsonify({"status": "error", "message": "Invalid command"}), 400

@app.route('/home', methods=['POST'])
def home_arm():
    if not ser:
        return jsonify({"status": "error", "message": "Serial not connected"}), 500
    
    ser.write(b"H\n")
    print("Sent: H (Homing)")
    return jsonify({"status": "success", "message": "Homing command sent"})

if __name__ == '__main__':
    app.run(debug=True, port=5001)
