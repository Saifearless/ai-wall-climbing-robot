// ESP32-WROOM-32 DevKit, L298N. Arduino-ESP32 core 3.x.
// BENCH TEST ONLY: 300 ms movement pulses; no climbing/suction control.
// Remove ENA/ENB jumpers; add 10k pull-downs on both enable pins.
#include <Arduino.h>

constexpr int IN1=26, IN2=27, IN3=32, IN4=33, ENA=25, ENB=14;
constexpr int TRIG=18, ECHO=19;
constexpr bool USE_HCSR04=false; // Enable ONLY after model/wiring verification.
// HC-SR04 Echo -> 1k resistor -> GPIO19 -> 2k resistor -> GND.
constexpr int TEST_DUTY=120; // 0..255. Start wheels lifted. May not move under load.
constexpr unsigned long PULSE_MS=300;
bool moving=false, pwmReady=false;
unsigned long started=0;

void stopMotors() {
  if (pwmReady) { ledcWrite(ENA,0); ledcWrite(ENB,0); }
  digitalWrite(IN1,LOW); digitalWrite(IN2,LOW);
  digitalWrite(IN3,LOW); digitalWrite(IN4,LOW);
  moving=false;
}

void moveMotors(int a, int b) {
  stopMotors();
  if (!pwmReady) { Serial.println("ERROR PWM unavailable"); return; }
  delay(10); // Brief disabled interval before changing direction.
  digitalWrite(IN1,a>0); digitalWrite(IN2,a<0);
  digitalWrite(IN3,b>0); digitalWrite(IN4,b<0);
  ledcWrite(ENA,a ? TEST_DUTY : 0); ledcWrite(ENB,b ? TEST_DUTY : 0);
  started=millis(); moving=true;
  Serial.println("MOVING 300ms");
}

void distanceReading() {
  stopMotors(); // This sensor test never runs while driving.
  if (!USE_HCSR04) { Serial.println("DISTANCE disabled: verify sensor first"); return; }
  digitalWrite(TRIG,LOW); delayMicroseconds(2);
  digitalWrite(TRIG,HIGH); delayMicroseconds(10); digitalWrite(TRIG,LOW);
  unsigned long duration=pulseIn(ECHO,HIGH,25000);
  if (!duration) { Serial.println("DISTANCE no valid echo"); return; }
  Serial.print("DISTANCE cm: "); Serial.println(duration*0.0343f/2.0f,1);
}

void setup() {
  pinMode(ENA,OUTPUT); pinMode(ENB,OUTPUT);
  digitalWrite(ENA,LOW); digitalWrite(ENB,LOW);
  pinMode(IN1,OUTPUT); pinMode(IN2,OUTPUT);
  pinMode(IN3,OUTPUT); pinMode(IN4,OUTPUT);
  stopMotors();
  Serial.begin(115200);
  bool a=ledcAttach(ENA,1000,8), b=ledcAttach(ENB,1000,8);
  if (a) ledcWrite(ENA,0);
  if (b) ledcWrite(ENB,0);
  pwmReady=a && b;
  if (USE_HCSR04) { pinMode(TRIG,OUTPUT); digitalWrite(TRIG,LOW); pinMode(ECHO,INPUT); }
  Serial.println(pwmReady ? "READY: a,b,f,v,l,r,s,d" : "ERROR: PWM setup failed; do not power motors");
}

void loop() {
  if (moving && millis()-started>=PULSE_MS) { stopMotors(); Serial.println("STOP timeout"); }
  if (!Serial.available()) return;
  char command=Serial.read();
  if (command=='\r' || command=='\n' || command==' ') return;
  switch (command) {
    case 'a': moveMotors(1,0); break;
    case 'b': moveMotors(0,1); break;
    case 'f': moveMotors(1,1); break;
    case 'v': moveMotors(-1,-1); break;
    case 'l': moveMotors(0,1); break;
    case 'r': moveMotors(1,0); break;
    case 's': stopMotors(); Serial.println("STOP"); break;
    case 'd': distanceReading(); break;
    default: stopMotors(); Serial.println("ERROR unknown command; stopped");
  }
}
