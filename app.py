import json
import os
import threading
import time
import uuid

import serial
from flask import Flask, jsonify, render_template, request

import config
from cv_detector import detect_color
from state_store import RuntimeStateStore

app = Flask(__name__)

POSITIONS_FILE = "positions.json"
WORKFLOWS_FILE = "workflows.json"
AUTOMATIONS_FILE = "automations.json"
STATE_FILE = "runtime_state.json"

HOME_ANGLES = {"B": 90, "S": 90, "E": 160, "W": 90, "R": 90, "G": 180, "M": 0}
JOINT_ORDER = ["B", "S", "E", "W", "R", "G", "M"]
WORKFLOW_STEP_DELAY_SECONDS = 0.2
LCD_TEMP_MESSAGE_MS = 2500
DEFAULT_DEMO_NAME = "Presentation Demo"
DEMO_CONVEYOR_SPEED = 128
DEMO_DETECT_DISTANCE_CM = 6
DEMO_STOP_DELAY_MS = 800
DEMO_REVERSE_SPEED = -200
DEMO_REVERSE_MS = 2000
DEMO_RED_WORKFLOW = "pd-red"
DEMO_GREEN_WORKFLOW = "pd-green"
DEFAULT_MOTOR_STOP_FACTOR = 150000
CAMERA_INDEX = 0
CAMERA_POLL_SECONDS = 0.25


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


automations_lock = threading.Lock()
ser1_lock = threading.Lock()
ser2_lock = threading.Lock()

automations_cache = load_automations()
automation_runtime = {}
ultrasonic_thread = None
camera_thread = None
demo_thread = None
demo_stop_event = threading.Event()
state_store = RuntimeStateStore(STATE_FILE, HOME_ANGLES)


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


def get_state_payload():
    payload = state_store.snapshot()
    payload["automations"] = serialize_automations()
    return payload


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


def compact_lcd_text(text, limit=16):
    clean = " ".join(str(text).strip().split())
    return clean[:limit]


def send_lcd_message(message, duration_ms=0):
    if ser1 is None:
        return

    command = f"LCD:{int(max(0, duration_ms))}:{compact_lcd_text(message)}\n"
    write_serial(ser1, command)
    print(f"Sent to Arduino 1: {command.strip()} [lcd]")


def send_joint_command(cmd_id, value, reason="manual"):
    target_ser, label = route_serial_for_command(cmd_id)
    if target_ser is None:
        raise RuntimeError(f"Serial for {cmd_id} not connected")

    command = f"{cmd_id}:{value}\n"
    write_serial(target_ser, command)
    state_store.record_joint_command(cmd_id.upper(), value, reason, label)
    print(f"Sent to {label}: {command.strip()} [{reason}]")
    return get_state_payload()


def send_home_command(reason="manual_home"):
    if ser1 is None and ser2 is None:
        raise RuntimeError("No Arduinos connected")

    send_lcd_message("ARM HOMING", 4000)

    targets = []
    if ser1:
        write_serial(ser1, "H\n")
        targets.append("Arduino 1")
        print("Sent to Arduino 1: H [home_arm]")
    if ser2:
        write_serial(ser2, "H\n")
        targets.append("Arduino 2")
        print("Sent to Arduino 2: H [home_arm]")

    state_store.record_home_command(reason, ", ".join(targets))
    return get_state_payload()


def move_to_angles(angles, label):
    for joint_id in JOINT_ORDER:
        if joint_id not in angles:
            continue
        send_joint_command(joint_id, angles[joint_id], reason=f"sequence:{label}")
        time.sleep(WORKFLOW_STEP_DELAY_SECONDS)


def compute_motor_wait_ms(speed, stop_factor=DEFAULT_MOTOR_STOP_FACTOR):
    speed = int(speed)
    stop_factor = int(stop_factor)

    if speed == 0:
        raise ValueError("Motor speed cannot be 0 for a speed-based motor step")
    if stop_factor <= 0:
        raise ValueError("Motor stop factor must be greater than 0")

    return max(1, int(stop_factor / abs(speed)))


def resolve_position(name):
    if name == "HOME":
        return dict(HOME_ANGLES)

    positions = load_positions()
    if name not in positions:
        raise ValueError(f"Position '{name}' not found")
    return positions[name]


def normalize_sequence_steps(steps):
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError("Workflow sequence must contain at least one step")

    normalized = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Workflow step must be an object")

        step_type = step.get("type")
        if step_type == "move":
            name = step.get("name")
            if not name:
                raise ValueError("Move steps require a position name")
            resolve_position(name)
            normalized.append({"type": "move", "name": name})
        elif step_type == "wait":
            duration = max(0, float(step.get("duration", 0)))
            normalized.append({"type": "wait", "duration": duration})
        elif step_type == "motor_run":
            speed = int(step.get("speed", 0))
            stop_factor = int(step.get("stop_factor", DEFAULT_MOTOR_STOP_FACTOR))
            wait_ms = compute_motor_wait_ms(speed, stop_factor)
            normalized.append({
                "type": "motor_run",
                "speed": speed,
                "stop_factor": stop_factor,
                "wait_ms": wait_ms,
            })
        else:
            raise ValueError(f"Unsupported step type '{step_type}'")

    return normalized


def execute_workflow_steps(steps, workflow_name, source):
    total_steps = len(steps)
    state_store.set_workflow_started(workflow_name, source, total_steps)
    print(f"Workflow started: {workflow_name} [{source}]")
    send_lcd_message(f"WF {workflow_name}", 0)

    try:
        for index, step in enumerate(steps, start=1):
            step_type = step.get("type")

            if step_type == "move":
                position_name = step.get("name")
                state_store.set_workflow_step(index, "move", position_name)
                send_lcd_message(f"{index} MOVE {position_name}", 0)
                angles = resolve_position(position_name)
                move_to_angles(angles, f"{workflow_name}:{position_name}")
            elif step_type == "wait":
                duration_seconds = max(0, float(step.get("duration", 0)))
                label = f"{duration_seconds}s"
                state_store.set_workflow_step(index, "wait", label)
                send_lcd_message(f"{index} WAIT {duration_seconds}s", 0)
                print(f"Workflow wait: {duration_seconds}s [{workflow_name}]")
                time.sleep(duration_seconds)
            elif step_type == "motor_run":
                speed = int(step["speed"])
                wait_ms = int(step.get("wait_ms") or compute_motor_wait_ms(speed, step.get("stop_factor", DEFAULT_MOTOR_STOP_FACTOR)))
                label = f"speed {speed} for {wait_ms}ms"
                state_store.set_workflow_step(index, "motor_run", label)
                send_lcd_message(f"{index} MOTOR {speed}", 0)
                print(f"Workflow motor run: speed {speed}, wait {wait_ms}ms [{workflow_name}]")
                send_joint_command("M", speed, reason=f"sequence:{workflow_name}:motor_run")
                time.sleep(wait_ms / 1000)
                send_joint_command("M", 0, reason=f"sequence:{workflow_name}:motor_stop")
                send_lcd_message("MOTOR AUTO STOP", 1800)

        state_store.set_workflow_complete(workflow_name)
        send_lcd_message("WF COMPLETE", 3500)
        print(f"Workflow completed: {workflow_name} [{source}]")
    except Exception as exc:
        state_store.set_workflow_failed(workflow_name, str(exc))
        send_lcd_message("WF ERROR", 3500)
        print(f"Workflow error: {workflow_name} [{source}] -> {exc}")
        raise


def run_sequence_async(steps, workflow_name, source="manual"):
    normalized_steps = normalize_sequence_steps(steps)
    worker = threading.Thread(
        target=execute_workflow_steps,
        args=(normalized_steps, workflow_name, source),
        daemon=True,
    )
    worker.start()


def run_saved_workflow_async(workflow_name, source="manual"):
    workflows = load_workflows()
    if workflow_name not in workflows:
        raise ValueError(f"Workflow '{workflow_name}' not found")

    run_sequence_async(workflows[workflow_name], workflow_name, source)


def run_motor_for_duration(speed, duration_ms, reason):
    send_joint_command("M", speed, reason=reason)
    time.sleep(max(0, duration_ms) / 1000)
    send_joint_command("M", 0, reason=f"{reason}:stop")


def execute_demo_mode(demo_name):
    state_store.set_demo_started(demo_name, "pd-red / pd-green")
    send_lcd_message("DEMO MODE", 0)
    print(f"Demo mode started: {demo_name}")

    try:
        send_home_command(reason="demo_mode_home")
        time.sleep(2.0)
        workflows = load_workflows()
        missing = [name for name in [DEMO_RED_WORKFLOW, DEMO_GREEN_WORKFLOW] if name not in workflows]
        if missing:
            raise ValueError(f"Missing demo workflow(s): {', '.join(missing)}")

        while not demo_stop_event.is_set():
            state_store.set_demo_phase("feeding", "Conveyor running at M:128")
            send_lcd_message("CONVEYOR 128", 0)
            send_joint_command("M", DEMO_CONVEYOR_SPEED, reason="demo_mode_feed")

            while not demo_stop_event.is_set():
                state = state_store.snapshot()
                distance_cm = state.get("sensor", {}).get("distance_cm")
                if distance_cm is not None and distance_cm < DEMO_DETECT_DISTANCE_CM:
                    break
                time.sleep(0.05)

            if demo_stop_event.is_set():
                break

            state_store.set_demo_phase("detected", f"Object detected under {DEMO_DETECT_DISTANCE_CM} cm")
            send_lcd_message("OBJECT DETECTED", 0)
            time.sleep(DEMO_STOP_DELAY_MS / 1000)
            send_joint_command("M", 0, reason="demo_mode_detect_stop")

            state = state_store.snapshot()
            color_name = (state.get("sensor", {}).get("color_name") or "UNKNOWN").upper()

            if color_name == "RED":
                state_store.set_demo_phase("red_branch", f"Running {DEMO_RED_WORKFLOW}")
                send_lcd_message("RED -> PD RED", 0)
                execute_workflow_steps(workflows[DEMO_RED_WORKFLOW], DEMO_RED_WORKFLOW, "demo_mode")
            elif color_name == "GREEN":
                state_store.set_demo_phase("green_branch", f"Running {DEMO_GREEN_WORKFLOW}")
                send_lcd_message("GRN -> PD GRN", 0)
                execute_workflow_steps(workflows[DEMO_GREEN_WORKFLOW], DEMO_GREEN_WORKFLOW, "demo_mode")
            else:
                state_store.set_demo_phase("reject_branch", f"Rejecting {color_name}")
                send_lcd_message(f"REJECT {color_name}", 0)
                run_motor_for_duration(DEMO_REVERSE_SPEED, DEMO_REVERSE_MS, "demo_mode_reject")

            state_store.set_demo_phase("restart_feed", "Restarting conveyor")
            send_lcd_message("RESTART FEED", 1200)
            time.sleep(0.3)

        send_joint_command("M", 0, reason="demo_mode_shutdown")
        state_store.set_demo_stopped(f"{demo_name} stopped")
        send_lcd_message("DEMO STOPPED", 2500)
        print(f"Demo mode stopped: {demo_name}")
    except Exception as exc:
        state_store.set_demo_failed(str(exc))
        try:
            send_joint_command("M", 0, reason="demo_mode_error_stop")
        except Exception:
            pass
        send_lcd_message("DEMO ERROR", 3500)
        print(f"Demo mode failed: {demo_name} -> {exc}")


def start_demo_mode_async(demo_name=DEFAULT_DEMO_NAME):
    global demo_thread
    state = state_store.snapshot()
    if state.get("demo", {}).get("status") == "running":
        raise RuntimeError("Demo mode is already running")

    demo_stop_event.clear()
    demo_thread = threading.Thread(
        target=execute_demo_mode,
        args=(demo_name,),
        daemon=True,
    )
    demo_thread.start()


def stop_demo_mode():
    state = state_store.snapshot()
    if state.get("demo", {}).get("status") != "running":
        raise RuntimeError("Demo mode is not running")

    demo_stop_event.set()


def execute_automation_action(automation):
    action_type = automation["action_type"]

    if action_type == "stop_motor":
        send_joint_command("M", 0, reason=f"automation:{automation['name']}")
        send_lcd_message("MOTOR STOPPED", 3500)
        return "Motor stopped"

    if action_type == "home_arm":
        send_home_command(reason=f"automation:{automation['name']}")
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
    pending_for = now + delay_seconds
    runtime["pending_for"] = pending_for
    runtime["last_result"] = f"Scheduled at {distance_cm:.1f} cm"
    state_store.set_automation_pending(
        automation_id,
        automation["name"],
        pending_for,
        f"Scheduled at {distance_cm:.1f} cm",
    )

    timer = threading.Timer(delay_seconds, fire_automation, args=(automation_id,))
    timer.daemon = True
    runtime["timer"] = timer
    timer.start()

    if delay_seconds > 0:
        send_lcd_message(f"AUTO IN {delay_seconds:.1f}s", int(delay_seconds * 1000) + 500)
    else:
        send_lcd_message("AUTO TRIGGERED", LCD_TEMP_MESSAGE_MS)

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
    state_store.clear_automation_pending()

    if automation is None or not automation.get("enabled", True):
        message = "Skipped because rule was removed or disabled"
        runtime["last_result"] = message
        runtime["last_completed_at"] = time.time()
        state_store.set_automation_result(automation_id, "", message)
        return

    try:
        result = execute_automation_action(automation)
        runtime["last_result"] = result
        state_store.set_automation_result(automation_id, automation["name"], result)
        print(f"Automation executed: {automation['name']} -> {result}")
    except Exception as exc:
        runtime["last_result"] = f"Error: {exc}"
        state_store.set_automation_result(automation_id, automation["name"], f"Error: {exc}")
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


def monitor_arduino_1_stream():
    while ser1:
        try:
            with ser1_lock:
                raw_line = ser1.readline()

            if not raw_line:
                time.sleep(0.02)
                continue

            line = raw_line.decode(errors="ignore").strip()
            if line.startswith("D:"):
                distance_cm = float(line.split(":", 1)[1])
                state_store.record_sensor(distance_cm, line)
                process_ultrasonic_distance(distance_cm)
                continue
        except Exception as exc:
            state_store.record_sensor_error(f"error: {exc}")
            print(f"Ultrasonic monitor error: {exc}")
            time.sleep(0.25)


def monitor_camera_color():
    try:
        import cv2
    except ImportError as exc:
        state_store.record_color("CV_UNAVAILABLE", 0, f"CV:{exc}")
        print(f"Camera color monitor unavailable: {exc}")
        return

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        state_store.record_color("CAMERA_OFFLINE", 0, "CV:camera_offline")
        print("Camera color monitor unavailable: camera not opened")
        return

    while True:
        try:
            ret, frame = cap.read()
            if not ret:
                state_store.record_color("CAMERA_READ_FAIL", 0, "CV:read_fail")
                time.sleep(CAMERA_POLL_SECONDS)
                continue

            result = detect_color(frame)
            state_store.record_color(
                result["color_name"],
                result["area"],
                f"CV:{result['color_name']}:{result['area']}",
            )
            time.sleep(CAMERA_POLL_SECONDS)
        except Exception as exc:
            state_store.record_color("CV_ERROR", 0, f"CV:{exc}")
            print(f"Camera color monitor error: {exc}")
            time.sleep(CAMERA_POLL_SECONDS)


def start_background_workers():
    global ultrasonic_thread
    global camera_thread

    if not ser1:
        state_store.record_sensor_error("arduino_1_not_connected")
    elif not ultrasonic_thread or not ultrasonic_thread.is_alive():
        ultrasonic_thread = threading.Thread(target=monitor_arduino_1_stream, daemon=True)
        ultrasonic_thread.start()
        print("Ultrasonic monitoring thread started")

    if not camera_thread or not camera_thread.is_alive():
        camera_thread = threading.Thread(target=monitor_camera_color, daemon=True)
        camera_thread.start()
        print("Camera color monitoring thread started")


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

state_store.set_connections(ser1 is not None, ser2 is not None)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/state", methods=["GET"])
@app.route("/sensor_state", methods=["GET"])
def get_state():
    return jsonify(get_state_payload())


@app.route("/send_command", methods=["POST"])
def send_command():
    data = request.json or {}
    cmd_id = data.get("id")
    value = data.get("value")

    if not cmd_id or value is None:
        return jsonify({"status": "error", "message": "Invalid command"}), 400

    try:
        state = send_joint_command(cmd_id, value)
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({"status": "success", "command": f"{cmd_id}:{value}", "state": state})


@app.route("/home", methods=["POST"])
def home_arm():
    try:
        state = send_home_command(reason="manual_home")
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({"status": "success", "message": "Home command sent", "state": state})


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

    normalized_steps = normalize_sequence_steps(steps)
    workflows = load_workflows()
    workflows[name] = normalized_steps
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

    return jsonify({"status": "success", "message": f"Workflow '{name}' started", "state": get_state_payload()})


@app.route("/run_sequence", methods=["POST"])
def run_sequence():
    data = request.json or {}
    steps = data.get("steps")
    name = (data.get("name") or "Draft Workflow").strip() or "Draft Workflow"

    try:
        run_sequence_async(steps, name, source="draft")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "success", "message": f"Sequence '{name}' started", "state": get_state_payload()})


@app.route("/demo_mode/start", methods=["POST"])
def start_demo_mode():
    try:
        start_demo_mode_async()
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409

    return jsonify({
        "status": "success",
        "message": "Hardcoded demo mode started",
        "state": get_state_payload(),
    })


@app.route("/demo_mode/stop", methods=["POST"])
def stop_demo_mode_route():
    try:
        stop_demo_mode()
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409

    return jsonify({
        "status": "success",
        "message": "Demo mode stop requested",
        "state": get_state_payload(),
    })


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
    return jsonify({"status": "success", "automation": automation, "state": get_state_payload()})


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
    return jsonify({"status": "success", "state": get_state_payload()})


if __name__ == "__main__":
    start_background_workers()
    app.run(debug=True, use_reloader=False, port=5001)
