# Software Viva Guide

This file is for quick preparation before the presentation and viva.

It explains:
- what the software does
- how the code is structured
- how the robot behaves
- what to say when asked technical questions

## 1. One-line explanation

This project is a software-controlled robotic sorting system where a web application controls a robotic arm and conveyor, reads sensors, and runs automation/workflow logic to sort objects based on detection and color.

## 2. Main software objective

The software has three goals:

1. Manual control
- allow the operator to move the robotic arm joints and motor from the browser

2. Automation
- react to sensor input like ultrasonic detection
- run predefined workflows automatically

3. Demo / sorting logic
- run a hardcoded demo loop:
  - start conveyor
  - detect object
  - stop conveyor
  - identify color
  - execute the correct workflow or reject path

## 3. High-level architecture

There are 4 major software parts:

### A. Frontend
- files:
  - [templates/index.html](./templates/index.html)
  - [static/script.js](./static/script.js)
  - [static/style.css](./static/style.css)

What it does:
- shows the dashboard
- lets the user move sliders
- save positions
- create workflows
- create automations
- start/stop demo mode
- displays live state from the backend

Important point:
- the frontend is **not** the main control brain
- it is only the operator interface

### B. Backend
- file:
  - [app.py](./app.py)

What it does:
- main control brain of the whole system
- talks to both Arduinos over serial
- runs workflows
- runs automations
- runs hardcoded demo mode
- reads ultrasonic input from Arduino 1
- reads color result from camera CV pipeline
- updates LCD status through Arduino 1
- exposes API endpoints to the UI

Important point:
- `app.py` is the central orchestrator

### C. Persistent runtime state
- file:
  - [state_store.py](./state_store.py)

What it does:
- stores live software state in `runtime_state.json`
- persists:
  - last commanded joints
  - sensor state
  - color state
  - workflow execution
  - automation state
  - demo state
  - command history

Why it exists:
- to avoid keeping important runtime state only in browser memory
- to survive page refresh or app restart

Important point:
- persisted state is used as software state, but not trusted as real physical feedback of arm pose

### D. Computer vision color detection
- files:
  - [cv_detector.py](./cv_detector.py)
  - [cv.py](./cv.py)
  - [camera_test.py](./camera_test.py)

What it does:
- uses webcam frames
- detects color using HSV ranges
- returns dominant color from the ROI

Important point:
- color detection is now camera-based, not Arduino color-sensor based

## 4. Hardware-software responsibility split

### Arduino 1
- file:
  - [main_1.ino](./main_1.ino)

Responsibilities:
- controls:
  - Base
  - Shoulder
  - Elbow
- reads ultrasonic sensor
- drives I2C LCD
- receives LCD text/status messages from backend

### Arduino 2
- file:
  - [main_2.ino](./main_2.ino)

Responsibilities:
- controls:
  - Wrist Pitch
  - Wrist Roll
  - Gripper
  - DC motor

### Key design choice

Arduino firmware is kept relatively simple.

The complex decision-making is in Python backend:
- workflows
- automations
- demo logic
- branch by color
- sensor-driven control

That is intentional because Python is easier to modify quickly during development.

## 5. How commands flow in the system

### Manual control flow

1. User moves slider in UI
2. Frontend sends `/send_command`
3. `app.py` decides which Arduino should receive the command
4. Serial command is sent
5. runtime state is updated
6. UI reflects updated backend state

### Workflow flow

1. User saves positions
2. User builds workflow from steps
3. Workflow is saved to `workflows.json`
4. User runs workflow
5. Backend executes steps sequentially

Supported workflow step types:
- `move`
- `wait`
- `motor_run`

### Automation flow

1. Arduino 1 sends ultrasonic distance
2. Backend reads distance
3. If rule condition matches:
  - backend schedules automation
4. After delay:
  - motor stop / home / workflow run

### Demo flow

The current hardcoded demo loop is:

1. Start conveyor at `M:128`
2. Wait until ultrasonic distance is below `6 cm`
3. Wait `1000 ms`
4. Stop motor
5. Check camera-detected color
6. Branch:
  - `RED` -> run `pd-red`
  - `GREEN` -> run `pd-green`
  - otherwise -> reverse motor `M:-200` for `1000 ms`
7. Restart conveyor
8. Repeat until stopped

## 6. Important data files

### `positions.json`
- stores saved robot poses

### `workflows.json`
- stores workflows made from steps

### `automations.json`
- stores ultrasonic trigger rules

### `runtime_state.json`
- stores persistent runtime state

## 7. Why backend-owned state was needed

Earlier, frontend memory was behaving like the source of truth.

That caused a serious robotics problem:
- old commanded state could get reapplied even if physical arm pose had changed

So the design was corrected:
- backend owns runtime state
- frontend reads backend state
- persisted pose is treated as informational, not guaranteed physical truth

This is a good viva point because it shows safety-aware design thinking.

## 8. Why color detection was moved away from Arduino logic

Originally, there was an attempt to classify color directly around Arduino-side sensor logic.

That was changed because:
- camera-based CV was easier to tune
- backend-side classification is easier to change than reflashing firmware repeatedly
- it keeps Arduino simpler

So now:
- camera sees object
- `cv_detector.py` classifies color
- backend stores that result
- demo logic uses that result

## 9. Most important files to mention in viva

If asked “which files matter most?”, answer:

### Core control
- [app.py](./app.py)
- [state_store.py](./state_store.py)

### UI
- [templates/index.html](./templates/index.html)
- [static/script.js](./static/script.js)

### Firmware
- [main_1.ino](./main_1.ino)
- [main_2.ino](./main_2.ino)

### Vision
- [cv_detector.py](./cv_detector.py)

## 10. Likely viva questions and safe answers

### Q. Why did you use two Arduinos?

Because the system has multiple servos, a conveyor motor, an ultrasonic sensor, LCD, and serial coordination. Splitting responsibilities made pin usage and task separation simpler:
- Arduino 1 handles structural joints + ultrasonic + LCD
- Arduino 2 handles wrist/gripper + DC motor

### Q. Why is Python backend needed?

Because the backend is the main control layer. It is easier to implement workflows, automations, state persistence, and demo branching in Python than in microcontroller firmware.

### Q. Why not do everything on Arduino?

Because higher-level orchestration is easier, faster to modify, and more maintainable in Python. Arduino is used for low-level actuation and sensor interfacing.

### Q. How is color detected?

Using a webcam and OpenCV-based HSV color detection in the software layer. The detected color is then used by the backend logic.

### Q. How is object presence detected?

Using the HC-SR04 ultrasonic sensor connected to Arduino 1. The distance is streamed to the backend over serial.

### Q. What happens when an object is detected in demo mode?

The conveyor is running. When distance goes below 6 cm, the backend waits 1000 ms, stops the motor, checks the camera-detected color, then runs the correct workflow or a reject motor action, and finally restarts the conveyor.

### Q. Why do you store runtime state?

To make the UI and backend consistent, preserve execution state across refresh/restart, and avoid depending only on browser memory.

### Q. Is persisted pose always equal to real robot pose?

No. Persisted pose is the last commanded software state. Without encoder feedback, physical pose is not guaranteed. That distinction is important for safety.

### Q. What is the role of the LCD?

It gives local machine feedback directly on the robot side:
- distance state
- workflow execution
- demo state
- automation status

### Q. What is future scope?

Full automatic color-based sorting with more reliable classification, richer workflow branching, and more autonomous pick-and-place behavior.

## 11. What your teammate must remember

If they remember only 5 points, remember these:

1. `app.py` is the brain
2. two Arduinos split low-level hardware control
3. ultrasonic detects object presence
4. camera CV detects color
5. hardcoded demo branches into red / green / reject actions

## 12. Short emergency answer

If someone asks suddenly, this answer is enough:

“Software-wise, the browser is only the interface. The main control logic is in the Flask backend, which talks to two Arduinos over serial, runs workflows and automations, reads ultrasonic input, gets color from OpenCV, and executes the sorting/demo logic. Runtime state is persisted so the system remains synchronized across sessions.”
