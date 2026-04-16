# Indera Robotic Arm - Mission Control

Mission Control is a browser-based control and automation system for a bench-top robotic arm with a conveyor motor, ultrasonic sensing, and an onboard I2C LCD status display.

It is designed for live operator control and short demo workflows: teach poses, build sequences, arm ultrasonic-trigger rules, and monitor execution from both the UI and the robot itself.

## Features

### Manual robot control
- Independent control of all arm joints: Base, Shoulder, Elbow, Wrist Pitch, Wrist Roll, and Gripper
- Bi-directional DC motor control with `M:-255` to `M:255`
- Emergency stop for the motor
- One-click homing for both Arduino-controlled sections of the robot
- Slider inactivity delay before send, plus explicit `Send Pending`

### Workflow system
- Save named robot poses in `positions.json`
- Build workflows from `move` and `wait` steps
- Run saved workflows from the UI
- Backend-owned workflow execution so running state is tracked outside the browser

### Demo mode
- One-click hardcoded presentation loop from the dashboard
- Starts the conveyor at `M:128`
- Waits for ultrasonic detection under `6 cm`
- Stops after `1000 ms`
- Branches by detected color:
  - `RED` -> run `pd-red`
  - `GREEN` -> run `pd-green`
  - otherwise reverse motor at `M:-200` for `1000 ms`
- Restarts the conveyor after each branch so the cycle can continue until stopped
- Demo state is tracked in the persistent runtime store so the UI can show phase, status, and last result

### Ultrasonic-trigger automations
- Live ultrasonic telemetry in the dashboard
- Create trigger rules such as:
  - if distance is below a threshold
  - wait a configurable delay
  - then stop the motor, home the arm, or run a workflow
- Per-rule cooldown, enable/disable state, and saved configuration in `automations.json`

### LCD execution display
- 16x2 I2C LCD connected to the ultrasonic Arduino
- Shows:
  - live distance / detected-clear state
  - workflow execution banners
  - automation countdowns
  - homing / stop messages
- Setup guide: [LCD_I2C_SETUP.md](./LCD_I2C_SETUP.md)

### Persistent runtime state
- Backend persists runtime state in `runtime_state.json`
- Stores:
  - last commanded joint targets
  - sensor state
  - workflow execution state
  - automation state
  - recent command history
- State survives browser refreshes and app restarts
- Persisted pose is treated as informational, not trusted physical feedback

## System architecture

### Arduino 1: structural joints + ultrasonic + LCD
- Firmware: [main_1.ino](./main_1.ino)
- Controls:
  - Base
  - Shoulder
  - Elbow
- Reads:
  - HC-SR04 ultrasonic sensor
- Drives:
  - I2C LCD status display

### Arduino 2: effector joints + motor
- Firmware: [main_2.ino](./main_2.ino)
- Controls:
  - Wrist Pitch
  - Wrist Roll
  - Gripper
  - DC motor through L298N

### Backend
- [app.py](./app.py)
- Flask API + serial bridge
- Owns runtime state and workflow execution

### State store
- [state_store.py](./state_store.py)
- Atomic JSON-backed runtime state persistence

## Serial protocol

The system uses a simple serial command protocol at `9600` baud.

| Command | Meaning | Example |
| :--- | :--- | :--- |
| `B:angle` | Base position | `B:90` |
| `S:angle` | Shoulder position | `S:120` |
| `E:angle` | Elbow position | `E:145` |
| `W:angle` | Wrist pitch position | `W:90` |
| `R:angle` | Wrist roll position | `R:90` |
| `G:angle` | Gripper position | `G:120` |
| `M:speed` | DC motor speed | `M:-200` |
| `H` | Home section | `H` |
| `D:distance` | Ultrasonic reading from Arduino 1 | `D:5` |

There is also an internal LCD-status serial message format used by the backend:

| Command | Meaning | Example |
| :--- | :--- | :--- |
| `LCD:<ms>:<text>` | Show LCD banner for duration or until replaced | `LCD:2500:MOTOR STOPPED` |
| `LCD:CLEAR` | Clear temporary LCD banner | `LCD:CLEAR` |

## Installation

### Python dependencies
```bash
pip install flask pyserial
```

### Configure serial ports
Update [config.py](./config.py) with the correct ports for:
- `SERIAL_PORT_1`
- `SERIAL_PORT_2`

### Flash the Arduinos
- Flash [main_1.ino](./main_1.ino) to Arduino 1
- Flash [main_2.ino](./main_2.ino) to Arduino 2

### Run the app
```bash
python app.py
```

Open:

```text
http://127.0.0.1:5001
```

## Runtime files

These files are created or used during operation:
- `positions.json`
- `workflows.json`
- `automations.json`
- `runtime_state.json`

## Project structure

```text
├── app.py
├── config.py
├── state_store.py
├── main.ino
├── main_1.ino
├── main_2.ino
├── automations.json
├── positions.json
├── workflows.json
├── runtime_state.json
├── templates/
│   └── index.html
├── static/
│   ├── script.js
│   └── style.css
└── LCD_I2C_SETUP.md
```

## Demo-ready highlights

For presentation, the strongest visible features are:
- live manual control from the dashboard
- saved pose + workflow execution
- ultrasonic-trigger automation
- one-click demo mode
- LCD showing workflow and automation status on the robot itself
