import json
import os
import threading
import time
import uuid

import serial
from flask import Flask, jsonify, render_template, request

import config

app = Flask(__name__)

POSITIONS_FILE = "positions.json"
WORKFLOWS_FILE = "workflows.json"
AUTOMATIONS_FILE = "automations.json"

HOME_ANGLES = {"B": 90, "S": 90, "E": 160, "W": 90, "R": 90, "G": 180, "M": 0}
JOINT_ORDER = ["B", "S", "E", "W", "R", "G", "M"]
WORKFLOW_STEP_DELAY_SECONDS = 0.2


def iso_timestamp(ts=None):
    timestamp = ts if ts is not None else time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp))


def load_data(filepath, default):
    if not os.path.exists(filepath):
        return default

    try:
        with open(filepath, "r") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return default


def save_data(filepath, data):
    with open(filepath, "w") as file:
        json.dump(data, file, indent=4)


def load_positions():
    return load_data(POSITIONS_FILE, {})


def save_positions(positions):
    save_data(POSITIONS_FILE, positions)


def load_workflows():
    return load_data(WORKFLOWS_FILE, {})


def load_automations():
    data = load_data(AUTOMATIONS_FILE, [])
    return data if isinstance(data, list) else []


def save_automations(automations):
    save_data(AUTOMATIONS_FILE, automations)


sensor_state_lock = threading.Lock()
automations_lock = threading.Lock()
ser1_lock = threading.Lock()
ser2_lock = threading.Lock()

sensor_state = {
    "distance_cm": None,
    "last_updated": None,
    "last_raw": None,
    "status": "idle",
}

automations_cache = load_automations()
automation_runtime = {}
ultrasonic_thread = None


def init_runtime_state():
    for automation in automations_cache:
        automation_runtime.setdefault(
            automation["id"],
            {
                "pending_for": None,
                "last_triggered_at": None,
                "last_completed_at": None,
                "last_result": None,
                "timer": None,
            },
        )


init_runtime_state()


def get_automation_by_id(automation_id):
    with automations_lock:
        for automation in automations_cache:
            if automation["id"] == automation_id:
                return dict(automation)
    return None


def refresh_automation_cache(automations):
    global automations_cache
    with automations_lock:
        automations_cache = automations
        active_ids = {automation["id"] for automation in automations_cache}

        for automation in automations_cache:
            automation_runtime.setdefault(
                automation["id"],
                {
                    "pending_for": None,
                    "last_triggered_at": None,
                    "last_completed_at": None,
                    "last_result": None,
                    "timer": None,
                },
            )

        for automation_id in list(automation_runtime.keys()):
            if automation_id not in active_ids:
                runtime = automation_runtime.pop(automation_id)
                timer = runtime.get("timer")
                if timer and timer.is_alive():
                    timer.cancel()


def serialize_automations():
    now = time.time()
    serialized = []

    with automations_lock:
        automations = [dict(automation) for automation in automations_cache]

    for automation in automations:
        runtime = automation_runtime.get(automation["id"], {})
        cooldown_ms = int(automation.get("cooldown_ms", 0) or 0)
        last_triggered_at = runtime.get("last_triggered_at")
        pending_for = runtime.get("pending_for")

        cooldown_remaining_ms = 0
        if last_triggered_at:
            elapsed_ms = int((now - last_triggered_at) * 1000)
            cooldown_remaining_ms = max(0, cooldown_ms - elapsed_ms)

        automation["runtime"] = {
            "pending_for": pending_for,
            "last_triggered_at": last_triggered_at,
            "last_completed_at": runtime.get("last_completed_at"),
            "last_result": runtime.get("last_result"),
            "cooldown_remaining_ms": cooldown_remaining_ms,
            "is_pending": bool(pending_for and pending_for > now),
        }
        serialized.append(automation)

    return serialized


def update_sensor_state(distance_cm, raw_line):
    with sensor_state_lock:
        sensor_state["distance_cm"] = distance_cm
        sensor_state["last_updated"] = time.time()
        sensor_state["last_raw"] = raw_line
        sensor_state["status"] = "tracking"


def get_sensor_state_payload():
    with sensor_state_lock:
        state = dict(sensor_state)

    state["automations"] = serialize_automations()
    return state


def route_serial_for_command(cmd_id):
    cmd_id = cmd_id.upper()
    if cmd_id in ["B", "S", "E"]:
        return ser1, "Arduino 1"
    if cmd_id in ["W", "R", "G", "M"]:
        return ser2, "Arduino 2"
    return None, None


def write_serial(target_ser, command):
    if target_ser is None:
        raise RuntimeError("Serial target not connected")

    lock = ser1_lock if target_ser == ser1 else ser2_lock
    with lock:
        target_ser.write(command.encode())


def send_joint_command(cmd_id, value, reason="manual"):
    target_ser, label = route_serial_for_command(cmd_id)
    if target_ser is None:
        raise RuntimeError(f"Serial for {cmd_id} not connected")

    command = f"{cmd_id}:{value}\n"
    write_serial(target_ser, command)
    print(f"Sent to {label}: {command.strip()} [{reason}]")


def send_home_command():
    if ser1 is None and ser2 is None:
        raise RuntimeError("No Arduinos connected")

    if ser1:
        write_serial(ser1, "H\n")
        print("Sent to Arduino 1: H [home_arm]")
    if ser2:
        write_serial(ser2, "H\n")
        print("Sent to Arduino 2: H [home_arm]")


def move_to_angles(angles, label):
    for joint_id in JOINT_ORDER:
        if joint_id not in angles:
            continue
        send_joint_command(joint_id, angles[joint_id], reason=f"sequence:{label}")
        time.sleep(WORKFLOW_STEP_DELAY_SECONDS)


def resolve_position(name):
    if name == "HOME":
        return dict(HOME_ANGLES)

    positions = load_positions()
    if name not in positions:
        raise ValueError(f"Position '{name}' not found")
    return positions[name]


def execute_workflow_steps(steps, workflow_name, source):
    print(f"Workflow started: {workflow_name} [{source}]")

    for step in steps:
        step_type = step.get("type")

        if step_type == "move":
            position_name = step.get("name")
            angles = resolve_position(position_name)
            move_to_angles(angles, f"{workflow_name}:{position_name}")
        elif step_type == "wait":
            duration_seconds = max(0, float(step.get("duration", 0)))
            print(f"Workflow wait: {duration_seconds}s [{workflow_name}]")
            time.sleep(duration_seconds)

    print(f"Workflow completed: {workflow_name} [{source}]")


def run_saved_workflow_async(workflow_name, source="manual"):
    workflows = load_workflows()
    if workflow_name not in workflows:
        raise ValueError(f"Workflow '{workflow_name}' not found")

    worker = threading.Thread(
        target=execute_workflow_steps,
        args=(workflows[workflow_name], workflow_name, source),
        daemon=True,
    )
    worker.start()


def execute_automation_action(automation):
    action_type = automation["action_type"]

    if action_type == "stop_motor":
        send_joint_command("M", 0, reason=f"automation:{automation['name']}")
        return "Motor stopped"

    if action_type == "home_arm":
        send_home_command()
        return "Home command sent"

    if action_type == "run_workflow":
        workflow_name = automation.get("workflow_name")
        if not workflow_name:
            raise ValueError("Workflow action requires a workflow")
        run_saved_workflow_async(workflow_name, source=f"automation:{automation['name']}")
        return f"Workflow '{workflow_name}' started"

    raise ValueError(f"Unsupported action '{action_type}'")


def schedule_automation(automation, distance_cm):
    automation_id = automation["id"]
    runtime = automation_runtime.setdefault(
        automation_id,
        {
            "pending_for": None,
            "last_triggered_at": None,
            "last_completed_at": None,
            "last_result": None,
            "timer": None,
        },
    )

    existing_timer = runtime.get("timer")
    if existing_timer and existing_timer.is_alive():
        return

    now = time.time()
    cooldown_seconds = max(0, int(automation.get("cooldown_ms", 0) or 0)) / 1000
    last_triggered_at = runtime.get("last_triggered_at")
    if last_triggered_at and (now - last_triggered_at) < cooldown_seconds:
        return

    delay_seconds = max(0, int(automation.get("delay_ms", 0) or 0)) / 1000
    runtime["pending_for"] = now + delay_seconds
    runtime["last_result"] = f"Scheduled at {distance_cm:.1f} cm"

    timer = threading.Timer(delay_seconds, fire_automation, args=(automation_id,))
    timer.daemon = True
    runtime["timer"] = timer
    timer.start()
    print(
        f"Automation scheduled: {automation['name']} in "
        f"{int(delay_seconds * 1000)} ms at {distance_cm:.1f} cm"
    )


def fire_automation(automation_id):
    automation = get_automation_by_id(automation_id)
    runtime = automation_runtime.get(automation_id)
    if runtime is None:
        return

    runtime["timer"] = None
    runtime["pending_for"] = None
    runtime["last_triggered_at"] = time.time()

    if automation is None or not automation.get("enabled", True):
        runtime["last_result"] = "Skipped because rule was removed or disabled"
        runtime["last_completed_at"] = time.time()
        return

    try:
        result = execute_automation_action(automation)
        runtime["last_result"] = result
        print(f"Automation executed: {automation['name']} -> {result}")
    except Exception as exc:
        runtime["last_result"] = f"Error: {exc}"
        print(f"Automation error: {automation['name']} -> {exc}")
    finally:
        runtime["last_completed_at"] = time.time()


def process_ultrasonic_distance(distance_cm):
    with automations_lock:
        automations = [dict(automation) for automation in automations_cache]

    for automation in automations:
        if not automation.get("enabled", True):
            continue

        if automation.get("sensor_type") != "ultrasonic":
            continue

        threshold_cm = float(automation.get("threshold_cm", 0))
        if distance_cm < threshold_cm:
            schedule_automation(automation, distance_cm)


def monitor_ultrasonic_distance():
    while ser1:
        try:
            with ser1_lock:
                raw_line = ser1.readline()

            if not raw_line:
                time.sleep(0.02)
                continue

            line = raw_line.decode(errors="ignore").strip()
            if not line.startswith("D:"):
                continue

            distance_cm = float(line.split(":", 1)[1])
            update_sensor_state(distance_cm, line)
            process_ultrasonic_distance(distance_cm)
        except Exception as exc:
            with sensor_state_lock:
                sensor_state["status"] = f"error: {exc}"
            print(f"Ultrasonic monitor error: {exc}")
            time.sleep(0.25)


def start_background_workers():
    global ultrasonic_thread

    if not ser1:
        with sensor_state_lock:
            sensor_state["status"] = "arduino_1_not_connected"
        return

    if ultrasonic_thread and ultrasonic_thread.is_alive():
        return

    ultrasonic_thread = threading.Thread(target=monitor_ultrasonic_distance, daemon=True)
    ultrasonic_thread.start()
    print("Ultrasonic monitoring thread started")


def sanitize_automation_payload(data):
    action_type = data.get("action_type")
    workflow_name = data.get("workflow_name", "").strip()

    automation = {
        "id": data.get("id") or str(uuid.uuid4()),
        "name": (data.get("name") or "").strip(),
        "sensor_type": "ultrasonic",
        "threshold_cm": float(data.get("threshold_cm", 0)),
        "delay_ms": int(data.get("delay_ms", 0)),
        "cooldown_ms": int(data.get("cooldown_ms", 0)),
        "action_type": action_type,
        "workflow_name": workflow_name,
        "enabled": bool(data.get("enabled", True)),
    }

    if not automation["name"]:
        raise ValueError("Automation name is required")
    if automation["threshold_cm"] <= 0:
        raise ValueError("Threshold must be greater than 0")
    if automation["delay_ms"] < 0:
        raise ValueError("Delay must be 0 or greater")
    if automation["cooldown_ms"] < 0:
        raise ValueError("Cooldown must be 0 or greater")
    if automation["action_type"] not in ["stop_motor", "home_arm", "run_workflow"]:
        raise ValueError("Unsupported action type")

    if automation["action_type"] == "run_workflow":
        workflows = load_workflows()
        if not workflow_name:
            raise ValueError("Select a workflow for this automation")
        if workflow_name not in workflows:
            raise ValueError(f"Workflow '{workflow_name}' not found")
    else:
        automation["workflow_name"] = ""

    return automation


# Initialize Serial Connections
try:
    ser1 = serial.Serial(config.SERIAL_PORT_1, config.BAUD_RATE, timeout=0.1)
    print(f"Connected to Arduino 1 on {config.SERIAL_PORT_1}")
except Exception as exc:
    print(f"Could not connect to Arduino 1: {exc}")
    ser1 = None

try:
    ser2 = serial.Serial(config.SERIAL_PORT_2, config.BAUD_RATE, timeout=0.1)
    print(f"Connected to Arduino 2 on {config.SERIAL_PORT_2}")
except Exception as exc:
    print(f"Could not connect to Arduino 2: {exc}")
    ser2 = None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sensor_state", methods=["GET"])
def get_sensor_state():
    return jsonify(get_sensor_state_payload())


@app.route("/send_command", methods=["POST"])
def send_command():
    data = request.json or {}
    cmd_id = data.get("id")
    value = data.get("value")

    if not cmd_id or value is None:
        return jsonify({"status": "error", "message": "Invalid command"}), 400

    try:
        send_joint_command(cmd_id, value)
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({"status": "success", "command": f"{cmd_id}:{value}"})


@app.route("/home", methods=["POST"])
def home_arm():
    try:
        send_home_command()
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({"status": "success", "message": "Home command sent"})


@app.route("/positions", methods=["GET"])
def get_positions():
    return jsonify(load_positions())


@app.route("/save_position", methods=["POST"])
def save_pos():
    data = request.json or {}
    name = data.get("name")
    angles = data.get("angles")

    if not name or not angles:
        return jsonify({"status": "error", "message": "Missing name or angles"}), 400

    positions = load_positions()
    positions[name] = angles
    save_positions(positions)
    return jsonify({"status": "success", "message": f"Position '{name}' saved"})


@app.route("/delete_position", methods=["POST"])
def delete_pos():
    name = (request.json or {}).get("name")
    positions = load_positions()

    if name in positions:
        del positions[name]
        save_positions(positions)
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Position not found"}), 404


@app.route("/workflows", methods=["GET"])
def get_workflows():
    return jsonify(load_workflows())


@app.route("/save_workflow", methods=["POST"])
def save_wf():
    data = request.json or {}
    name = data.get("name")
    steps = data.get("steps")

    if not name or steps is None:
        return jsonify({"status": "error", "message": "Missing name or steps"}), 400

    workflows = load_workflows()
    workflows[name] = steps
    save_data(WORKFLOWS_FILE, workflows)
    return jsonify({"status": "success", "message": f"Workflow '{name}' saved"})


@app.route("/delete_workflow", methods=["POST"])
def delete_wf():
    name = (request.json or {}).get("name")
    workflows = load_workflows()

    if name in workflows:
        del workflows[name]
        save_data(WORKFLOWS_FILE, workflows)
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Workflow not found"}), 404


@app.route("/run_workflow", methods=["POST"])
def run_workflow():
    name = (request.json or {}).get("name")
    if not name:
        return jsonify({"status": "error", "message": "Workflow name is required"}), 400

    try:
        run_saved_workflow_async(name, source="api")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404

    return jsonify({"status": "success", "message": f"Workflow '{name}' started"})


@app.route("/automations", methods=["GET"])
def get_automations():
    return jsonify(serialize_automations())


@app.route("/save_automation", methods=["POST"])
def save_automation():
    data = request.json or {}

    try:
        automation = sanitize_automation_payload(data)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    with automations_lock:
        updated = False
        new_automations = []

        for existing in automations_cache:
            if existing["id"] == automation["id"]:
                new_automations.append(automation)
                updated = True
            else:
                new_automations.append(existing)

        if not updated:
            new_automations.append(automation)

    save_automations(new_automations)
    refresh_automation_cache(new_automations)
    return jsonify({"status": "success", "automation": automation})


@app.route("/delete_automation", methods=["POST"])
def delete_automation():
    automation_id = (request.json or {}).get("id")
    if not automation_id:
        return jsonify({"status": "error", "message": "Automation id is required"}), 400

    with automations_lock:
        new_automations = [
            automation for automation in automations_cache if automation["id"] != automation_id
        ]

    if len(new_automations) == len(automations_cache):
        return jsonify({"status": "error", "message": "Automation not found"}), 404

    save_automations(new_automations)
    refresh_automation_cache(new_automations)
    return jsonify({"status": "success"})


if __name__ == "__main__":
    start_background_workers()
    app.run(debug=True, use_reloader=False, port=5001)
