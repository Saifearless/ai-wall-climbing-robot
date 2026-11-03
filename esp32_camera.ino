// AI Thinker ESP32-CAM (OV2640) ONLY. Arduino-ESP32 core 3.x.
// MB board is the USB programmer/power adapter, not a separate firmware target.
// Simple snapshot server; browser refreshes images. No AI and no motor control.
#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

const char* WIFI_NAME="YOUR_WIFI_NAME";
const char* WIFI_PASSWORD="YOUR_WIFI_PASSWORD";
WebServer server(80);

void capture() {
  camera_fb_t* frame=esp_camera_fb_get();
  if (!frame) { server.send(503,"text/plain","Camera capture failed"); return; }
  server.sendHeader("Cache-Control","no-store");
  server.setContentLength(frame->len);
  server.send(200,"image/jpeg","");
  WiFiClient client=server.client();
  size_t sent=0; unsigned long began=millis();
  while (sent<frame->len && client.connected() && millis()-began<3000) {
    size_t count=frame->len-sent;
    if (count>1024) count=1024;
    size_t n=client.write(frame->buf+sent,count);
    if (!n) break;
    sent+=n;
  }
  if (sent<frame->len) client.stop();
  esp_camera_fb_return(frame);
}

void setup() {
  Serial.begin(115200);
  pinMode(4,OUTPUT); digitalWrite(4,LOW); // Keep bright flash LED off.
  camera_config_t c={};
  c.ledc_channel=LEDC_CHANNEL_0; c.ledc_timer=LEDC_TIMER_0;
  c.pin_d0=5; c.pin_d1=18; c.pin_d2=19; c.pin_d3=21;
  c.pin_d4=36; c.pin_d5=39; c.pin_d6=34; c.pin_d7=35;
  c.pin_xclk=0; c.pin_pclk=22; c.pin_vsync=25; c.pin_href=23;
  c.pin_sccb_sda=26; c.pin_sccb_scl=27; c.pin_pwdn=32; c.pin_reset=-1;
  c.xclk_freq_hz=20000000; c.pixel_format=PIXFORMAT_JPEG;
  c.frame_size=FRAMESIZE_VGA; c.jpeg_quality=12; c.fb_count=1;
  c.fb_location=psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  esp_err_t result=esp_camera_init(&c);
  if (result!=ESP_OK) {
    Serial.printf("Camera error 0x%x: check camera model/ribbon/power\n",result);
    while(true) delay(1000);
  }
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_NAME,WIFI_PASSWORD);
  Serial.print("Joining 2.4GHz Wi-Fi");
  unsigned long began=millis();
  while (WiFi.status()!=WL_CONNECTED && millis()-began<30000) { delay(500); Serial.print('.'); }
  if (WiFi.status()!=WL_CONNECTED) {
    Serial.println("\nWi-Fi failed. Check credentials and reset.");
    while(true) delay(1000);
  }
  server.on("/",HTTP_GET,[](){
    server.send(200,"text/html",R"HTML(<!doctype html><meta name="viewport" content="width=device-width"><title>Robot camera</title><h2>Robot camera - snapshots</h2><img id="cam" width="640" style="max-width:100%"><script>const im=document.getElementById('cam');function next(){im.src='/capture?t='+Date.now()}im.onload=()=>setTimeout(next,500);im.onerror=()=>setTimeout(next,1500);next();</script>)HTML");
  });
  server.on("/capture",HTTP_GET,capture);
  server.begin(); Serial.print("\nCamera URL: http://"); Serial.println(WiFi.localIP());
}

void loop() { server.handleClient(); delay(2); }
