#include <Servo.h>

// Array of Servo objects (Wrist Pit, Wrist Roll, Gripper)
Servo servos[3];

// Servo Pins: WristPitch, WristRoll, Gripper
const int servoPins[3] = {5, 6, 7};

// Names for printing
const String servoNames[3] = {"Wrist Pitch", "Wrist Roll", "Gripper"};

// Safe limits [min, max]
const int minLimit[3] = {0, 0, 80};
const int maxLimit[3] = {180, 180, 180};

// Home positions   
const int homePos[3] = {90, 90, 180};

// Track current positions
int curPos[3] = {90, 90, 180};

// Movement parameters
const int stepSize = 1;       // Degrees per step
const int stepDelay = 15;     // Milliseconds between steps

// DC Motor L298N pins
const int MOTOR_IN1 = 12;     // Direction pin 1
const int MOTOR_IN2 = 13;     // Direction pin 2
const int MOTOR_ENA = 11;     // PWM speed control

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

void setup() {
  Serial.begin(9600);
  
  // Attach all servos and set them to their home positions immediately
  for(int i = 0; i < 3; i++) {
    servos[i].attach(servoPins[i]);
    curPos[i] = homePos[i];
    servos[i].write(curPos[i]); // Initial snap to home position
  }
  
  // Setup DC motor pins
  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);
  pinMode(MOTOR_ENA, OUTPUT);
  
  controlMotor(0);
  

  
  delay(1000);
  Serial.println("Arduino 2 (Wrist/Gripper/Motor) Online");
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
  Serial.println("Homing Effector Joints...");
  smoothMove(0, homePos[0]); delay(100);
  smoothMove(1, homePos[1]); delay(100);
  smoothMove(2, homePos[2]);
  Serial.println("Effector Joints Homing Complete.");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    
    if (cmd.length() == 0) return;
    
    char motorID = cmd.charAt(0);
    
    // 1. Home Command
    if (motorID == 'H' || motorID == 'h') {
      homeArm();
      return;
    }
    
    // 2. DC Motor Command
    if (motorID == 'M' || motorID == 'm') {
      int colonIdx = cmd.indexOf(':');
      if (colonIdx != -1) {
        int speed = cmd.substring(colonIdx + 1).toInt();
        controlMotor(speed);
      }
      return;
    }
    
    // 3. Servo Command
    int servoIndex = -1;
    switch (motorID) {
      case 'W': case 'w': servoIndex = 0; break;
      case 'R': case 'r': servoIndex = 1; break;
      case 'G': case 'g': servoIndex = 2; break;
    }
    
    if (servoIndex != -1) {
      int colonIdx = cmd.indexOf(':');
      if (colonIdx != -1) {
        int targetAngle = cmd.substring(colonIdx + 1).toInt();
        smoothMove(servoIndex, targetAngle);
      }
    }
  }
}
