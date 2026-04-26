import subprocess
import base64
import json
import time
import requests
from datetime import datetime

FRAME_PATH = "/Users/tanayshah/drone/snapshot.jpg"

class AnomalyDetector:
    def __init__(self):
        self.alert_log = []
        self.baseline = None
        self.alert_threshold = "low"

    def capture_frame(self):
        result = subprocess.run([
            'ffmpeg', '-f', 'avfoundation',
            '-pixel_format', 'uyvy422',
            '-framerate', '30',
            '-video_size', '640x480',
            '-i', '0',
            '-vframes', '1',
            '-update', '1',
            FRAME_PATH, '-y'
        ], capture_output=True)
        return result.returncode == 0

    def analyze(self, base64_image):
        response = requests.post('http://localhost:11434/api/chat', json={
            "model": "llava",
            "messages": [{
                "role": "user",
                "content": """You are an anomaly detection AI for a drone fleet.
Analyze this aerial image and detect anything unusual, dangerous, or requiring attention.

Respond ONLY with this JSON:
{
  "anomaly_detected": true/false,
  "type": "fire/flood/person/debris/structural/wildlife/none",
  "severity": "none/low/medium/high/critical",
  "location": "describe where in the frame",
  "description": "one sentence",
  "recommended_action": "hover/investigate/alert/land/avoid"
}""",
                "images": [base64_image]
            }],
            "stream": False
        })

        text = response.json()['message']['content'].strip()
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return None

    def trigger_alert(self, anomaly):
        timestamp = datetime.now().strftime("%H:%M:%S")
        alert = {
            "time": timestamp,
            "type": anomaly.get("type", "unknown"),
            "severity": anomaly.get("severity", "unknown"),
            "location": anomaly.get("location", "unknown"),
            "description": anomaly.get("description", ""),
            "action": anomaly.get("recommended_action", "hover")
        }
        self.alert_log.append(alert)

        severity = anomaly.get("severity", "none")
        alert_type = anomaly.get("type", "unknown")

        print(f"\n🚨 ANOMALY ALERT [{timestamp}]")
        print(f"   Type:     {alert_type.upper()}")
        print(f"   Severity: {severity.upper()}")
        print(f"   Location: {anomaly.get('location', '?')}")
        print(f"   Details:  {anomaly.get('description', '?')}")
        print(f"   Action:   {anomaly.get('recommended_action', '?').upper()}")

        # Speak alert for critical/high
        if severity in ["critical", "high"]:
            msg = f"Alert. {alert_type} detected. {anomaly.get('description', '')}. Initiating {anomaly.get('recommended_action', 'hover')} protocol."
            subprocess.run(['say', '-v', 'Samantha', msg], capture_output=True)

        return alert

    def run(self, cycles=10, use_snapshot=True):
        print("🔍 ANOMALY DETECTION SYSTEM ACTIVE")
        print(f"   Monitoring {cycles} frames\n")

        for i in range(cycles):
            print(f"[SCAN {i+1}/{cycles}] Analyzing frame...", end=" ")

            if not use_snapshot:
                if not self.capture_frame():
                    print("Capture failed")
                    continue

            with open(FRAME_PATH, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode()

            result = self.analyze(image_data)

            if result:
                if result.get("anomaly_detected"):
                    print(f"⚠️  ANOMALY DETECTED")
                    self.trigger_alert(result)
                else:
                    print(f"✓ Clear — {result.get('description', 'No anomalies')}")
            else:
                print("Could not parse response")

            time.sleep(2)

        print(f"\n📊 SESSION COMPLETE")
        print(f"   Total scans:   {cycles}")
        print(f"   Alerts fired:  {len(self.alert_log)}")

        if self.alert_log:
            print(f"\n   Alert summary:")
            for alert in self.alert_log:
                print(f"   [{alert['time']}] {alert['type'].upper()} — {alert['severity'].upper()}")

if __name__ == "__main__":
    detector = AnomalyDetector()
    # Use existing snapshot so camera conflict doesn't block us
    detector.run(cycles=5, use_snapshot=True)