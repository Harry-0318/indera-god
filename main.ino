#include <Servo.h>

// Array of Servo objects
Servo servos[6];

// Servo Pins: Base, Shoulder, Elbow, WristPitch, WristRoll, Gripper
const int servoPins[6] = {2, 3, 4, 5, 6, 7};

// Names for printing
const String servoNames[6] = {"Base", "Shoulder", "Elbow", "Wrist Pitch", "Wrist Roll", "Gripper"};

// Safe limits [min, max]
const int minLimit[6] = {0, 20, 15, 0, 0, 80};
const int maxLimit[6] = {180, 160, 165, 180, 180, 180};

// Home positions   
const int homePos[6] = {90, 90, 160, 90, 90, 180};

// Track current positions
int curPos[6] = {90, 90, 90, 90, 90, 180};

// Movement parameters
const int stepSize = 1;       // Degrees per step
const int stepDelay = 15;     // Milliseconds between steps

// DC Motor L298N pins
const int MOTOR_IN1 = 12;     // Direction pin 1
const int MOTOR_IN2 = 13;     // Direction pin 2
const int MOTOR_ENA = 11;     // PWM speed control (Important: Using 11, not 9)

void setup() {
  Serial.begin(9600);
  
  // Attach all servos and set them to their home positions immediately
  for(int i = 0; i < 6; i++) {
    servos[i].attach(servoPins[i]);
    curPos[i] = homePos[i];
    servos[i].write(curPos[i]); // Initial snap to home position
  }
  
  // Setup DC motor pins
  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);
  pinMode(MOTOR_ENA, OUTPUT);
  
  // Start with motor disabled
  controlMotor(0);
  
  // Wait a moment for things to settle
  delay(1000);
  
  // Print interactive menu
  printMenu();
}

void printMenu() {
  Serial.println("\n========================================");
  Serial.println("Robotic Arm Controller - Interactive Mode");
  Serial.println("========================================");
  Serial.println("Servo commands (Format -> X:angle):");
  Serial.println("  B:angle  - Move Base (0-180)");
  Serial.println("  S:angle  - Move Shoulder (20-160)");
  Serial.println("  E:angle  - Move Elbow (15-165)");
  Serial.println("  W:angle  - Move Wrist pitch (0-180)");
  Serial.println("  R:angle  - Move Wrist roll (0-180)");
  Serial.println("  G:angle  - Move Gripper (120-180)");
  Serial.println("  H        - Home position");
  Serial.println("\nDC Motor commands:");
  Serial.println("  M:speed  - Motor speed (-255 to 255)");
  Serial.println("             Negative = reverse, 0 = stop");
  Serial.println("----------------------------------------");
  Serial.print("Enter command: ");
}

void controlMotor(int speed) {
  int pwm = abs(speed);
  pwm = constrain(pwm, 0, 255);
  
  if (speed > 0) {
    digitalWrite(MOTOR_IN1, HIGH);
    digitalWrite(MOTOR_IN2, LOW);
  } else if (speed < 0) {
    digitalWrite(MOTOR_IN1, LOW);
    digitalWrite(MOTOR_IN2, HIGH);
  } else {
    digitalWrite(MOTOR_IN1, LOW);
    digitalWrite(MOTOR_IN2, LOW);
  }
  
  analogWrite(MOTOR_ENA, pwm);
}

void smoothMove(int servoIndex, int target) {
  // Constrain target within safe limits
  target = constrain(target, minLimit[servoIndex], maxLimit[servoIndex]);
  
  Serial.print("Moving ");
  Serial.print(servoNames[servoIndex]);
  Serial.print(" from ");
  Serial.print(curPos[servoIndex]);
  Serial.print(" to ");
  Serial.print(target);
  Serial.print("... ");
  
  // Move up
  while (curPos[servoIndex] < target) {
    curPos[servoIndex] += stepSize;
    if (curPos[servoIndex] > target) curPos[servoIndex] = target;
    servos[servoIndex].write(curPos[servoIndex]);
    delay(stepDelay);
  }
  
  // Move down
  while (curPos[servoIndex] > target) {
    curPos[servoIndex] -= stepSize;
    if (curPos[servoIndex] < target) curPos[servoIndex] = target;
    servos[servoIndex].write(curPos[servoIndex]);
    delay(stepDelay);
  }
  
  Serial.println("Done!");
}

void homeArm() {
  Serial.println("Homing arm...");
  delay(100);
  
  smoothMove(0, homePos[0]); delay(100);
  // smoothMove(1, homePos[1]); // Commented out to match original Python logic
  smoothMove(2, homePos[2]); delay(100);
  smoothMove(3, homePos[3]); delay(100);
  smoothMove(4, homePos[4]); delay(100);
  smoothMove(5, homePos[5]);
  
  Serial.println("Home position reached.");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();     // Remove accidental extra spaces or \r
    
    // Ignore empty lines
    if (cmd.length() == 0) return;
    
    char motorID = cmd.charAt(0);
    
    // 1. Home Command
    if (motorID == 'H' || motorID == 'h') {
      homeArm();
      Serial.print("\nEnter command: ");
      return;
    }
    
    // 2. DC Motor Command
    if (motorID == 'M' || motorID == 'm') {
      int colonIdx = cmd.indexOf(':');
      if (colonIdx != -1) {
        int speed = cmd.substring(colonIdx + 1).toInt();
        controlMotor(speed);
        Serial.print("Motor command executed. Speed: ");
        Serial.print(speed);
        Serial.println("/255");
      } else {
        Serial.println("Invalid motor format. Use M:speed (e.g. M:200)");
      }
      Serial.print("\nEnter command: ");
      return;
    }
    
    // 3. Servo Command
    int servoIndex = -1;
    switch (motorID) {
      case 'B': case 'b': servoIndex = 0; break;
      case 'S': case 's': servoIndex = 1; break;
      case 'E': case 'e': servoIndex = 2; break;
      case 'W': case 'w': servoIndex = 3; break;
      case 'R': case 'r': servoIndex = 4; break;
      case 'G': case 'g': servoIndex = 5; break;
    }
    
    if (servoIndex != -1) {
      int colonIdx = cmd.indexOf(':');
      if (colonIdx != -1) {
        int targetAngle = cmd.substring(colonIdx + 1).toInt();
        smoothMove(servoIndex, targetAngle);
      } else {
        Serial.println("Invalid servo format. Use X:angle (e.g. B:90)");
      }
    } else {
      Serial.println("Invalid command. Please check format.");
    }
    
    // Prompt again
    Serial.print("\nEnter command: ");
  }
}
