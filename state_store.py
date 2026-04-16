import copy
import json
import os
import threading
import time


def iso_timestamp(ts=None):
    timestamp = ts if ts is not None else time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp))


class RuntimeStateStore:
    def __init__(self, path, home_angles):
        self.path = path
        self.home_angles = {key: int(value) for key, value in home_angles.items()}
        self.lock = threading.Lock()
        self.state = self._load_or_default()

        with self.lock:
            self._recover_inflight_state()
            self._persist_locked()

    def _default_state(self):
        now = iso_timestamp()
        return {
            "version": 1,
            "updated_at": now,
            "session_started_at": now,
            "connections": {
                "arduino_1_connected": False,
                "arduino_2_connected": False,
            },
            "joints": dict(self.home_angles),
            "pose": {
                "status": "unverified",
                "last_commanded_at": None,
                "note": "Pose is not trusted until the robot is re-homed or manually re-synced.",
            },
            "sensor": {
                "distance_cm": None,
                "detected": False,
                "color_name": "UNKNOWN",
                "color_source": "cv",
                "color_area": 0,
                "color_last_updated": None,
                "last_updated": None,
                "last_raw": None,
                "status": "idle",
            },
            "execution": {
                "workflow_status": "idle",
                "active_workflow": None,
                "workflow_source": None,
                "started_at": None,
                "completed_at": None,
                "current_step_index": None,
                "current_step_type": None,
                "current_step_label": None,
                "total_steps": 0,
                "last_completed_workflow": None,
                "last_error": None,
            },
            "automation": {
                "pending_id": None,
                "pending_name": None,
                "pending_for": None,
                "last_triggered_id": None,
                "last_triggered_name": None,
                "last_result": None,
                "last_updated": None,
            },
            "demo": {
                "status": "idle",
                "phase": "idle",
                "active_name": None,
                "workflow_name": None,
                "started_at": None,
                "completed_at": None,
                "last_result": None,
            },
            "last_command": {
                "id": None,
                "value": None,
                "reason": None,
                "target": None,
                "at": None,
            },
            "command_log": [],
        }

    def _load_or_default(self):
        if not os.path.exists(self.path):
            return self._default_state()

        try:
            with open(self.path, "r") as file:
                loaded = json.load(file)
        except (OSError, json.JSONDecodeError):
            return self._default_state()

        state = self._default_state()
        self._merge_dict(state, loaded if isinstance(loaded, dict) else {})
        return state

    def _merge_dict(self, base, incoming):
        for key, value in incoming.items():
            if key not in base:
                continue

            if isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_dict(base[key], value)
            else:
                base[key] = value

    def _recover_inflight_state(self):
        execution = self.state["execution"]
        if execution["workflow_status"] == "running":
            execution["workflow_status"] = "interrupted"
            execution["completed_at"] = iso_timestamp()
            execution["last_error"] = "Interrupted by application restart"
            execution["active_workflow"] = None
            execution["workflow_source"] = None
            execution["current_step_index"] = None
            execution["current_step_type"] = None
            execution["current_step_label"] = None
            execution["total_steps"] = 0

        automation = self.state["automation"]
        if automation["pending_id"] or automation["pending_for"]:
            automation["pending_id"] = None
            automation["pending_name"] = None
            automation["pending_for"] = None
            automation["last_result"] = "Pending automation cleared on restart"
            automation["last_updated"] = iso_timestamp()

        demo = self.state["demo"]
        if demo["status"] == "running":
            demo["status"] = "interrupted"
            demo["phase"] = "interrupted"
            demo["completed_at"] = iso_timestamp()
            demo["last_result"] = "Demo interrupted by application restart"
            demo["active_name"] = None

        self.state["pose"]["status"] = "unverified"
        self.state["pose"]["note"] = "Pose is not trusted after restart until re-homed or manually re-synced."

    def _persist_locked(self):
        self.state["updated_at"] = iso_timestamp()
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w") as file:
            json.dump(self.state, file, indent=4)
        os.replace(temp_path, self.path)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def mutate(self, mutator):
        with self.lock:
            mutator(self.state)
            self._persist_locked()
            return copy.deepcopy(self.state)

    def set_connections(self, arduino_1_connected, arduino_2_connected):
        def apply(state):
            state["connections"]["arduino_1_connected"] = bool(arduino_1_connected)
            state["connections"]["arduino_2_connected"] = bool(arduino_2_connected)

        return self.mutate(apply)

    def record_joint_command(self, cmd_id, value, reason, target):
        def apply(state):
            state["joints"][cmd_id] = value
            state["pose"]["status"] = "assumed_from_commands"
            state["pose"]["last_commanded_at"] = iso_timestamp()
            state["pose"]["note"] = "Pose is inferred from sent commands, not measured from feedback."
            state["last_command"] = {
                "id": cmd_id,
                "value": value,
                "reason": reason,
                "target": target,
                "at": iso_timestamp(),
            }
            state["command_log"].append(copy.deepcopy(state["last_command"]))
            state["command_log"] = state["command_log"][-50:]

        return self.mutate(apply)

    def record_home_command(self, reason, targets):
        def apply(state):
            state["joints"] = dict(self.home_angles)
            state["pose"]["status"] = "homed_commanded"
            state["pose"]["last_commanded_at"] = iso_timestamp()
            state["pose"]["note"] = "Pose was reset by a home command and is assumed to match the robot."
            state["last_command"] = {
                "id": "H",
                "value": "HOME",
                "reason": reason,
                "target": targets,
                "at": iso_timestamp(),
            }
            state["command_log"].append(copy.deepcopy(state["last_command"]))
            state["command_log"] = state["command_log"][-50:]

        return self.mutate(apply)

    def record_sensor(self, distance_cm, raw_line, status="tracking"):
        def apply(state):
            state["sensor"]["distance_cm"] = distance_cm
            state["sensor"]["detected"] = bool(distance_cm is not None and 0 < distance_cm < 6)
            state["sensor"]["last_updated"] = iso_timestamp()
            state["sensor"]["last_raw"] = raw_line
            state["sensor"]["status"] = status

        return self.mutate(apply)

    def record_color(self, color_name, area, raw_line):
        def apply(state):
            state["sensor"]["color_name"] = color_name
            state["sensor"]["color_area"] = int(area)
            state["sensor"]["color_last_updated"] = iso_timestamp()
            state["sensor"]["last_raw"] = raw_line

        return self.mutate(apply)

    def record_sensor_error(self, status):
        def apply(state):
            state["sensor"]["status"] = status

        return self.mutate(apply)

    def set_workflow_started(self, workflow_name, source, total_steps):
        def apply(state):
            state["execution"] = {
                **state["execution"],
                "workflow_status": "running",
                "active_workflow": workflow_name,
                "workflow_source": source,
                "started_at": iso_timestamp(),
                "completed_at": None,
                "current_step_index": None,
                "current_step_type": None,
                "current_step_label": None,
                "total_steps": int(total_steps),
                "last_error": None,
            }

        return self.mutate(apply)

    def set_workflow_step(self, step_index, step_type, label):
        def apply(state):
            state["execution"]["current_step_index"] = int(step_index)
            state["execution"]["current_step_type"] = step_type
            state["execution"]["current_step_label"] = label

        return self.mutate(apply)

    def set_workflow_complete(self, workflow_name):
        def apply(state):
            state["execution"]["workflow_status"] = "completed"
            state["execution"]["active_workflow"] = None
            state["execution"]["workflow_source"] = None
            state["execution"]["completed_at"] = iso_timestamp()
            state["execution"]["current_step_index"] = None
            state["execution"]["current_step_type"] = None
            state["execution"]["current_step_label"] = None
            state["execution"]["total_steps"] = 0
            state["execution"]["last_completed_workflow"] = workflow_name

        return self.mutate(apply)

    def set_workflow_failed(self, workflow_name, error_message):
        def apply(state):
            state["execution"]["workflow_status"] = "error"
            state["execution"]["active_workflow"] = None
            state["execution"]["workflow_source"] = None
            state["execution"]["completed_at"] = iso_timestamp()
            state["execution"]["current_step_index"] = None
            state["execution"]["current_step_type"] = None
            state["execution"]["current_step_label"] = None
            state["execution"]["total_steps"] = 0
            state["execution"]["last_error"] = f"{workflow_name}: {error_message}"

        return self.mutate(apply)

    def set_automation_pending(self, automation_id, automation_name, pending_for, detail):
        def apply(state):
            state["automation"]["pending_id"] = automation_id
            state["automation"]["pending_name"] = automation_name
            state["automation"]["pending_for"] = pending_for
            state["automation"]["last_result"] = detail
            state["automation"]["last_updated"] = iso_timestamp()

        return self.mutate(apply)

    def clear_automation_pending(self):
        def apply(state):
            state["automation"]["pending_id"] = None
            state["automation"]["pending_name"] = None
            state["automation"]["pending_for"] = None
            state["automation"]["last_updated"] = iso_timestamp()

        return self.mutate(apply)

    def set_automation_result(self, automation_id, automation_name, result):
        def apply(state):
            state["automation"]["pending_id"] = None
            state["automation"]["pending_name"] = None
            state["automation"]["pending_for"] = None
            state["automation"]["last_triggered_id"] = automation_id
            state["automation"]["last_triggered_name"] = automation_name
            state["automation"]["last_result"] = result
            state["automation"]["last_updated"] = iso_timestamp()

        return self.mutate(apply)

    def set_demo_started(self, demo_name, workflow_name):
        def apply(state):
            state["demo"]["status"] = "running"
            state["demo"]["phase"] = "starting"
            state["demo"]["active_name"] = demo_name
            state["demo"]["workflow_name"] = workflow_name
            state["demo"]["started_at"] = iso_timestamp()
            state["demo"]["completed_at"] = None
            state["demo"]["last_result"] = "Demo sequence started"

        return self.mutate(apply)

    def set_demo_completed(self, result):
        def apply(state):
            state["demo"]["status"] = "completed"
            state["demo"]["phase"] = "completed"
            state["demo"]["active_name"] = None
            state["demo"]["completed_at"] = iso_timestamp()
            state["demo"]["last_result"] = result

        return self.mutate(apply)

    def set_demo_failed(self, result):
        def apply(state):
            state["demo"]["status"] = "error"
            state["demo"]["phase"] = "error"
            state["demo"]["active_name"] = None
            state["demo"]["completed_at"] = iso_timestamp()
            state["demo"]["last_result"] = result

        return self.mutate(apply)

    def set_demo_phase(self, phase, result=None):
        def apply(state):
            state["demo"]["phase"] = phase
            if result is not None:
                state["demo"]["last_result"] = result

        return self.mutate(apply)

    def set_demo_stopped(self, result):
        def apply(state):
            state["demo"]["status"] = "stopped"
            state["demo"]["phase"] = "stopped"
            state["demo"]["active_name"] = None
            state["demo"]["completed_at"] = iso_timestamp()
            state["demo"]["last_result"] = result

        return self.mutate(apply)
