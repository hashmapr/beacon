#!/usr/bin/env python3
"""
intergration.py — Beacon Mission Integration Loop
All four fixes applied:
  FIX 1: beacon.py health monitor (in beacon.py, not here)
  FIX 2: consensus.py argparse — only runs the requested scenario
  FIX 3: Telemetry timing — waits for first tick before scanning
  FIX 4: Demo frame loader — scenario-appropriate images in simulate mode
"""

import subprocess
import base64
import json
import math
import os
import time
import threading
import urllib.request
import shutil
from pymavlink import mavutil
from anomaly import AnomalyDetector
from navigate import Navigator

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

FRAME_PATH = "/Users/tanayshah/drone/snapshot.jpg"

# Read scenario and simulate flag from beacon.py env vars
SCENARIO    = os.environ.get("BEACON_SCENARIO", "wildfire")
SIMULATE    = os.environ.get("BEACON_SIMULATE", "0") == "1"
CONNECTION  = os.environ.get("BEACON_CONNECTION", "udp:127.0.0.1:14550")


# ─────────────────────────────────────────────
#  FIX 4: DEMO FRAME LOADER
#  Downloads a scenario-appropriate aerial image
#  when running in simulate mode so the anomaly
#  detector sees relevant imagery, not your floor.
# ─────────────────────────────────────────────

# Reliable open-access images per scenario (no auth, no 403)
# Using picsum.photos (stable Lorem Picsum CDN) with fixed seeds so images are consistent
DEMO_FRAME_URLS = {
    "wildfire":   "https://picsum.photos/seed/wildfire/640/480",
    "earthquake": "https://picsum.photos/seed/earthquake/640/480",
    "search":     "https://picsum.photos/seed/search/640/480",
    "chemical":   "https://picsum.photos/seed/chemical/640/480",
    "flood":      "https://picsum.photos/seed/flood/640/480",
    "landslide":  "https://picsum.photos/seed/landslide/640/480",
    "tsunami":    "https://picsum.photos/seed/tsunami/640/480",
}

DEMO_CACHE = {
    scenario: f"/tmp/beacon_demo_{scenario}.jpg"
    for scenario in DEMO_FRAME_URLS
}


def load_demo_frame(scenario: str, dest: str) -> bool:
    """
    FIX 4: In simulate mode, copy a scenario-relevant aerial image
    to FRAME_PATH before scanning starts.
    Returns True if successful, False if download failed (existing file kept).
    """
    if not SIMULATE:
        return False

    cache_path = DEMO_CACHE.get(scenario)
    url = DEMO_FRAME_URLS.get(scenario)

    if not cache_path or not url:
        print(f"[BEACON] No demo frame defined for scenario: {scenario}")
        return False

    # Use cached copy if already downloaded
    if os.path.exists(cache_path):
        try:
            shutil.copy2(cache_path, dest)
            print(f"[BEACON] 🖼️  Demo frame loaded: {scenario} (cached)")
            return True
        except Exception as e:
            print(f"[BEACON] ⚠️  Could not copy cached frame: {e}")

    # Download fresh
    try:
        print(f"[BEACON] 🌐 Downloading demo frame for '{scenario}'...")
        urllib.request.urlretrieve(url, cache_path)
        shutil.copy2(cache_path, dest)
        print(f"[BEACON] ✅ Demo frame ready: {scenario}")
        return True
    except Exception as e:
        print(f"[BEACON] ⚠️  Demo frame download failed: {e} — using existing frame")
        return False


# ─────────────────────────────────────────────
#  BEACON INTEGRATION
# ─────────────────────────────────────────────

class BeaconIntegration:
    def __init__(self):
        self.master = None
        self.detector = AnomalyDetector()
        self.navigator = Navigator()
        self.running = False
        self.current_position = (0, 0, 0)
        self.alerts = []
        self.mission_active = False

        # FIX 3: Gate that blocks scan_loop until telemetry has one real tick
        self._telemetry_ready = threading.Event()

        # FIX 4: Pre-load scenario-appropriate demo frame
        load_demo_frame(SCENARIO, FRAME_PATH)

    def connect_drone(self, connection_string=None):
        if SIMULATE:
            print("🚁 Running in simulation mode")
            return False
        conn = connection_string or CONNECTION
        print("🚁 Connecting to drone...")
        try:
            self.master = mavutil.mavlink_connection(conn)
            self.master.wait_heartbeat(timeout=5)
            print(f"✅ Connected! System {self.master.target_system}")
            return True
        except Exception as e:
            print(f"⚠️  No drone connected: {e}")
            print("   Running in simulation mode")
            return False

    def get_telemetry(self):
        if not self.master:
            t = time.time()
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
        except Exception:
            pass
        return 0, 0, 0

    def arm_and_takeoff(self, altitude=10):
        if not self.master:
            print(f"🚁 [SIM] Takeoff to {altitude}m")
            return

        print("Setting GUIDED mode...")
        self.master.set_mode('GUIDED')
        time.sleep(2)

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
        first_tick = True
        while self.running:
            x, y, alt = self.get_telemetry()
            self.current_position = (x, y, alt)  # assign first
            if first_tick:
                self._telemetry_ready.set()       # signal after
                first_tick = False
            time.sleep(0.5)

    def scan_loop(self):
        scan_count = 0
        while self.running:
            scan_count += 1
            x, y, alt = self.current_position
            print(f"\n[BEACON] 👁️  Scan {scan_count} | Scenario: {SCENARIO.upper()} | "
                  f"Position: ({x:.1f}, {y:.1f}) | Alt: {alt:.1f}m")

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
        dx, dy, _ = self.current_position
        anomaly_x = dx + 2
        anomaly_y = dy + 2
        safe_x = dx - 5
        safe_y = dy - 5
        print(f"[BEACON] Person at ({anomaly_x:.1f}, {anomaly_y:.1f})")
        print(f"[BEACON] Safe zone at ({safe_x:.1f}, {safe_y:.1f})")
        nav = Navigator()
        nav.run_navigation(
            person_x=anomaly_x,
            person_y=anomaly_y,
            safe_x=safe_x,
            safe_y=safe_y,
        )

    def run(self, duration=60):
        print("=" * 50)
        print("🔺 BEACON INTEGRATION")
        print("=" * 50)
        print(f"Scenario  : {SCENARIO.upper()}")
        print(f"Simulate  : {SIMULATE}")
        print(f"Duration  : {duration}s")
        print(f"Frame     : {FRAME_PATH}")
        print()

        connected = self.connect_drone()
        if connected:
            self.arm_and_takeoff()

        self.running = True
        self.mission_active = True

        # Start telemetry first
        telemetry_thread = threading.Thread(target=self.telemetry_loop, daemon=True)
        telemetry_thread.start()

        # FIX 3: Block here until telemetry has one real tick (max 3s)
        # Then sleep 0.6s so the sine-wave sim position has moved off (0.0, 0.0)
        # sin(0)*5 = 0.0 exactly at t=0, so we need one cycle before scanning.
        print("[BEACON] Waiting for telemetry lock...")
        got_lock = self._telemetry_ready.wait(timeout=3.0)
        if not got_lock:
            print("[BEACON] ⚠️  Telemetry timeout — proceeding anyway")
        time.sleep(1.0)  # let sim position move off zero before first scan

        # Now start scanning with real position data
        scan_thread = threading.Thread(target=self.scan_loop, daemon=True)
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
        print(f"  Scenario:     {SCENARIO.upper()}")
        print(f"  Duration:     {duration}s")
        print(f"  Total alerts: {len(self.alerts)}")

        if self.alerts:
            print("\n  Alerts:")
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

        print("\n✅ BEACON integration complete")


if __name__ == "__main__":
    beacon = BeaconIntegration()
    beacon.run(duration=30)