import subprocess
import base64
import json
import time
import threading
from pymavlink import mavutil
from anomaly import AnomalyDetector
from navigate import Navigator

FRAME_PATH = "/Users/tanayshah/drone/snapshot.jpg"

class BeaconIntegration:
    def __init__(self):
        self.master = None
        self.detector = AnomalyDetector()
        self.navigator = Navigator()
        self.running = False
        self.current_position = (0, 0, 0)  # x, y, altitude
        self.alerts = []
        self.mission_active = False

    def connect_drone(self, connection_string='udp:127.0.0.1:14550'):
        print("🚁 Connecting to drone...")
        try:
            self.master = mavutil.mavlink_connection(connection_string)
            self.master.wait_heartbeat(timeout=5)
            print(f"✅ Connected! System {self.master.target_system}")
            return True
        except Exception as e:
            print(f"⚠️  No drone connected: {e}")
            print("   Running in simulation mode")
            return False

    def get_telemetry(self):
        if not self.master:
            # Simulate position for testing
            t = time.time()
            import math
            x = math.sin(t * 0.1) * 5
            y = math.cos(t * 0.1) * 5
            alt = 10.0
            return x, y, alt

        try:
            msg = self.master.recv_match(
                type='GLOBAL_POSITION_INT',
                blocking=True,
                timeout=1
            )
            if msg:
                x = msg.lon / 1e7
                y = msg.lat / 1e7
                alt = msg.relative_alt / 1000.0
                return x, y, alt
        except:
            pass
        return 0, 0, 0

    def arm_and_takeoff(self, altitude=10):
        if not self.master:
            print("🚁 [SIM] Takeoff to 10m")
            return

        print("Arming...")
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 1, 0, 0, 0, 0, 0, 0
        )
        time.sleep(3)

        print(f"Taking off to {altitude}m...")
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, 0, 0, 0, 0, 0, altitude
        )
        time.sleep(8)
        print("✅ Airborne!")

    def telemetry_loop(self):
        while self.running:
            x, y, alt = self.get_telemetry()
            self.current_position = (x, y, alt)
            time.sleep(0.5)

    def scan_loop(self):
        scan_count = 0
        while self.running:
            scan_count += 1
            print(f"\n[BEACON] 👁️  Scan {scan_count} | Position: ({self.current_position[0]:.1f}, {self.current_position[1]:.1f}) | Alt: {self.current_position[2]:.1f}m")

            try:
                with open(FRAME_PATH, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode()

                result = self.detector.analyze(image_data)

                if result and result.get("anomaly_detected"):
                    alert = self.detector.trigger_alert(result)
                    self.alerts.append(alert)

                    severity = result.get("severity", "none")
                    if severity in ["high", "critical"]:
                        print(f"\n[BEACON] 🚨 HIGH PRIORITY ANOMALY — Initiating navigation")
                        self.handle_critical_anomaly(result)

                else:
                    desc = result.get("description", "Clear") if result else "Analysis failed"
                    print(f"[BEACON] ✓ {desc}")

            except Exception as e:
                print(f"[BEACON] Scan error: {e}")

            time.sleep(3)

    def handle_critical_anomaly(self, anomaly):
        print("\n[BEACON] 📍 Calculating rescue path...")

        # Get current drone position as reference
        dx, dy, _ = self.current_position

        # Anomaly detected ahead of drone
        anomaly_x = dx + 2
        anomaly_y = dy + 2

        # Safe extraction point
        safe_x = dx - 5
        safe_y = dy - 5

        print(f"[BEACON] Person at ({anomaly_x:.1f}, {anomaly_y:.1f})")
        print(f"[BEACON] Safe zone at ({safe_x:.1f}, {safe_y:.1f})")

        # Run navigation
        nav = Navigator()
        nav.run_navigation(
            person_x=anomaly_x,
            person_y=anomaly_y,
            safe_x=safe_x,
            safe_y=safe_y
        )

    def run(self, duration=60):
        print("=" * 50)
        print("🔺 BEACON INTEGRATION TEST")
        print("=" * 50)
        print(f"Duration: {duration} seconds")
        print(f"Frame: {FRAME_PATH}")
        print()

        # Connect to drone
        connected = self.connect_drone()

        if connected:
            self.arm_and_takeoff()

        self.running = True
        self.mission_active = True

        # Start telemetry thread
        telemetry_thread = threading.Thread(target=self.telemetry_loop)
        telemetry_thread.daemon = True
        telemetry_thread.start()

        # Start scan thread
        scan_thread = threading.Thread(target=self.scan_loop)
        scan_thread.daemon = True
        scan_thread.start()

        print(f"\n[BEACON] Mission running for {duration} seconds...")
        print("[BEACON] Press Ctrl+C to stop early\n")

        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("\n[BEACON] Mission interrupted")

        self.running = False
        time.sleep(1)

        print("\n" + "=" * 50)
        print("📊 MISSION SUMMARY")
        print("=" * 50)
        print(f"  Duration:     {duration}s")
        print(f"  Total alerts: {len(self.alerts)}")

        if self.alerts:
            print(f"\n  Alerts:")
            for a in self.alerts:
                print(f"  [{a['time']}] {a['type'].upper()} — {a['severity'].upper()} — {a['description'][:50]}")

        if connected and self.master:
            print("\n🛬 Landing...")
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_NAV_LAND,
                0, 0, 0, 0, 0, 0, 0, 0
            )

        print("\n✅ BEACON integration test complete")

if __name__ == "__main__":
    beacon = BeaconIntegration()
    beacon.run(duration=30)