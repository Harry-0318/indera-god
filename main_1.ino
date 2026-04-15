#include <Servo.h>

// Array of Servo objects (only 3 for this board)
Servo servos[3];

// Servo Pins: Base, Shoulder, Elbow
const int servoPins[3] = {2, 3, 4};

// Names for printing
const String servoNames[3] = {"Base", "Shoulder", "Elbow"};

// Safe limits [min, max]
const int minLimit[3] = {0, 20, 15};
const int maxLimit[3] = {180, 160, 165};

// Home positions   
const int homePos[3] = {90, 90, 160};

// Track current positions
int curPos[3] = {90, 90, 90};

// Movement parameters
const int stepSize = 1;       // Degrees per step
const int stepDelay = 15;     // Milliseconds between steps

// Ultrasonic Sensor Pins
const int trigPin = 8;
const int echoPin = 9;
unsigned long lastMeasureTime = 0;
const int measureInterval = 200; // Measure distance every 200ms

void setup() {
  Serial.begin(9600);
  
  // Attach all servos and set them to their home positions immediately
  for(int i = 0; i < 3; i++) {
    servos[i].attach(servoPins[i]);
    curPos[i] = homePos[i];
    servos[i].write(curPos[i]); // Initial snap to home position
  }
  
  // Setup HC-SR04
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  
  delay(1000);
  Serial.println("Arduino 1 (Base/Shoulder/Elbow + Ultrasonic) Online");
}

void measureDistance() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  
  long duration = pulseIn(echoPin, HIGH, 30000); // 30ms timeout
  int distance = duration * 0.034 / 2;
  
  if (distance > 0 && distance < 400) {
    // Print distance in a format the PC can easily parse: D:xx
    Serial.print("D:");
    Serial.println(distance);
  }
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
  Serial.println("Homing Structural Joints...");
  smoothMove(0, homePos[0]); delay(100);
  smoothMove(1, homePos[1]); delay(100);
  smoothMove(2, homePos[2]);
  Serial.println("Structural Joints Homing Complete.");
}

void loop() {
  // Periodically measure distance
  if (millis() - lastMeasureTime > measureInterval) {
    measureDistance();
    lastMeasureTime = millis();
  }

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
    
    // 2. Servo Command
    int servoIndex = -1;
    switch (motorID) {
      case 'B': case 'b': servoIndex = 0; break;
      case 'S': case 's': servoIndex = 1; break;
      case 'E': case 'e': servoIndex = 2; break;
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
