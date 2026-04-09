# Indera Robotic Arm - Mission Control

A high-performance, safety-first control system for a 6-DOF Robotic Arm with DC motor integration. This project bridges an Arduino-based hardware controller with a premium Python web interface.

## 🚀 Features

### **1. Premium "Mission Control" Interface**
- **Glassmorphic Design**: A modern, dark-themed UI with translucent panels and glowing accents for high visual clarity.
- **Dynamic Visual Feedback**: Smooth interactive elements and real-time command logging.
- **Responsive Layout**: Designed to work on desktops and tablets for field or desk operation.

### **2. Safety-First Movement Logic**
- **Inactivity Delay (3s)**: To prevent accidental mechanical strain, commands are only transmitted after the user has stopped moving the slider for 3 seconds.
- **Visual Countdown**: Real-time progress bars on each slider card indicate when the command is about to fire.
- **Manual Overrides**: Instant transmission via `SPACE` or `ENTER` keys, and a dedicated **Emergency Stop** for the DC motor.

### **3. Full Hardware Control**
- **6-DOF Optimization**: Individual control for Base, Shoulder, Elbow, Wrist Pitch, Wrist Roll, and Gripper.
- **DC Motor Integration**: Bi-directional speed control (-255 to 255) for base rotation or auxiliary tracks.
- **Smart Homing**: Single-button reset (`H` key) to return the arm to its safe rest position.

## 🛠 Technical Stack

- **Hardware**: Arduino (ATMega328P), Servo Motors, DC Motor (L298N Driver).
- **Firmware**: Arduino C++ with Serial interrupt handling.
- **Backend**: Python 3.8+ with **Flask** for API management and **PySerial** for hardware bridge.
- **Frontend**: HTML5, CSS3 (Vanilla), and JavaScript.

## 📡 Communication Protocol

The system uses a lightweight string-based protocol over Serial (9600 Baud):

| Command | Meaning | Example |
| :--- | :--- | :--- |
| `B:angle` | Base Position | `B:90` |
| `S:angle` | Shoulder Position | `S:120` |
| `M:speed` | DC Motor Speed | `M:-200` |
| `H` | Home All Joints | `H` |

## ⚙️ Installation & Setup

### 1. Hardware Setup (Arduino)
Flash the `main.ino` file to your Arduino. Ensure the servos are connected to pins **2-7** and the Motor Driver to **11, 12, 13**.

### 2. Software Configuration
Update the `SERIAL_PORT` in `config.py` to match your device (e.g., `COM3` or `/dev/cu.usbserial-110`).

### 3. Install Dependencies
```bash
pip install flask pyserial
```

### 4. Launch
```bash
python app.py
```
Visit `http://127.0.0.1:5001` in your browser.

## 🧱 Project Architecture
```text
├── app.py           # Flask Backend & Serial Bridge
├── config.py        # Port & Baudrate Configuration
├── main.ino         # Arduino Firmware
├── templates/       # HTML Dashboard
└── static/         
    ├── style.css    # Premium CSS Design
    └── script.js    # Inactivity Logic & Shortcuts
```
