#!/usr/bin/env python3
"""
beacon.py — Beacon Autonomous Disaster Response System
Single entry point. One command launches everything.

Usage:
    python beacon.py                          # Interactive mode
    python beacon.py --scenario wildfire      # Launch wildfire scenario
    python beacon.py --scenario earthquake    # Launch earthquake scenario
    python beacon.py --scenario search        # Launch search and rescue
    python beacon.py --scenario chemical      # Launch chemical plume scenario
    python beacon.py --scenario flood         # Launch flood assessment
    python beacon.py --scenario landslide     # Launch landslide assessment
    python beacon.py --scenario tsunami       # Launch tsunami assessment
    python beacon.py --dashboard-only         # Launch dashboard only
    python beacon.py --simulate               # Simulation mode (no drone hardware)
    python beacon.py --config config.json     # Load custom config
    python beacon.py --list-scenarios         # List all available scenarios
    python beacon.py --generate-config        # Write default config.json and exit
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List


# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

log_filename = LOG_DIR / f"beacon_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout),
    ],
)

log = logging.getLogger("beacon")


# ─────────────────────────────────────────────
#  DEFAULT CONFIG
# ─────────────────────────────────────────────

DEFAULT_CONFIG = {
    "drone": {
        "connection_string": "udp:127.0.0.1:14550",
        "simulate": False,
        "takeoff_altitude_m": 10,
        "max_altitude_m": 120,
        "return_home_on_fail": True,
    },
    "dashboard": {
        "host": "0.0.0.0",
        "port": 8080,
        "enabled": True,
    },
    "models": {
        "consensus": True,
        "farsite": True,
        "hazus": True,
        "slosh": True,
        "most": True,
        "trigrs": True,
        "aloha": True,
        "windninja": True,
        "shakemap": True,
        "pager": True,
    },
    "feeds": {
        "noaa": True,
        "usgs": True,
        "nasa_firms": True,
        "dart_buoy": True,
    },
    "mission": {
        "scan_interval_s": 3,
        "alert_threshold": "medium",
        "log_to_file": True,
        "generate_report": True,
    },
}


@dataclass
class BeaconConfig:
    drone_connection: str = "udp:127.0.0.1:14550"
    simulate: bool = False
    takeoff_altitude: float = 10.0
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    dashboard_enabled: bool = True
    scan_interval: int = 3
    generate_report: bool = True
    raw: dict = field(default_factory=lambda: DEFAULT_CONFIG)

    @classmethod
    def from_file(cls, path: str) -> "BeaconConfig":
        with open(path) as f:
            data = json.load(f)
        cfg = cls()
        cfg.drone_connection = data.get("drone", {}).get("connection_string", cfg.drone_connection)
        cfg.simulate        = data.get("drone", {}).get("simulate", cfg.simulate)
        cfg.takeoff_altitude = data.get("drone", {}).get("takeoff_altitude_m", cfg.takeoff_altitude)
        cfg.dashboard_host  = data.get("dashboard", {}).get("host", cfg.dashboard_host)
        cfg.dashboard_port  = data.get("dashboard", {}).get("port", cfg.dashboard_port)
        cfg.dashboard_enabled = data.get("dashboard", {}).get("enabled", cfg.dashboard_enabled)
        cfg.scan_interval   = data.get("mission", {}).get("scan_interval_s", cfg.scan_interval)
        cfg.generate_report = data.get("mission", {}).get("generate_report", cfg.generate_report)
        cfg.raw = data
        log.info(f"Config loaded from {path}")
        return cfg

    def save(self, path: str = "config.json"):
        with open(path, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        log.info(f"Default config saved to {path}")


# ─────────────────────────────────────────────
#  SCENARIOS
# ─────────────────────────────────────────────

SCENARIOS = {
    "wildfire": {
        "name": "Wildfire Perimeter Mapping",
        "description": "Map active fire perimeter, predict spread via FARSITE + Rothermel + WindNinja, identify survivors with thermal + anomaly detection.",
        "models": ["farsite", "rothermel", "windninja", "consensus"],
        "feeds": ["noaa", "nasa_firms"],
        "demo_location": {"lat": 40.1, "lon": -121.4},
        "entry": "intergration.py",
    },
    "earthquake": {
        "name": "Earthquake Structural Assessment",
        "description": "Post-earthquake damage assessment using ShakeMap + HAZUS + PAGER. Drone surveys collapsed structures, AI detects survivors.",
        "models": ["shakemap", "hazus", "pager", "aftershock", "consensus"],
        "feeds": ["usgs"],
        "demo_location": {"lat": 34.05, "lon": -118.25},
        "entry": "intergration.py",
    },
    "search": {
        "name": "Search and Rescue (Lost Hiker)",
        "description": "Mattson SAR probability model generates search zones. Drone autonomously sweeps terrain, anomaly detector identifies heat signatures.",
        "models": ["mattson", "consensus"],
        "feeds": ["noaa"],
        "demo_location": {"lat": 37.86, "lon": -119.54},
        "entry": "intergration.py",
    },
    "chemical": {
        "name": "Chemical Plume Tracking",
        "description": "ALOHA dispersion model maps hazard zones. Drone monitors plume boundary in real time. Evacuation zones auto-generated.",
        "models": ["aloha", "windninja", "consensus"],
        "feeds": ["noaa"],
        "demo_location": {"lat": 29.38, "lon": -94.90},
        "entry": "intergration.py",
    },
    "flood": {
        "name": "Flood and Storm Surge Assessment",
        "description": "HEC-RAS river flooding + SLOSH storm surge combined. Drone maps inundation extents and identifies stranded victims.",
        "models": ["hec_ras", "slosh", "consensus"],
        "feeds": ["noaa", "usgs"],
        "demo_location": {"lat": 29.75, "lon": -95.37},
        "entry": "intergration.py",
    },
    "landslide": {
        "name": "Landslide Risk Assessment",
        "description": "TRIGRS slope stability model identifies failure zones. Drone surveys terrain, maps debris field, locates buried victims.",
        "models": ["trigrs", "consensus"],
        "feeds": ["usgs", "noaa"],
        "demo_location": {"lat": 37.20, "lon": -121.98},
        "entry": "intergration.py",
    },
    "tsunami": {
        "name": "Tsunami Coastal Assessment",
        "description": "MOST wave propagation + DART buoy real-time data. Drone pre-positions to assess coastal impact zones immediately after wave arrival.",
        "models": ["most", "slosh", "consensus"],
        "feeds": ["noaa", "dart_buoy", "usgs"],
        "demo_location": {"lat": 38.80, "lon": 142.37},
        "entry": "intergration.py",
    },
}


# ─────────────────────────────────────────────
#  PROCESS MANAGER
#  FIX 1: health_check prunes dead processes
#  instead of spamming warnings about them forever
# ─────────────────────────────────────────────

class ProcessManager:
    def __init__(self):
        self.processes: List[subprocess.Popen] = []
        self._lock = threading.Lock()

    def spawn(self, cmd: List[str], name: str, env: dict = None) -> Optional[subprocess.Popen]:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env or os.environ.copy(),
            )
            with self._lock:
                self.processes.append(proc)
            log.info(f"[{name}] started (PID {proc.pid})")
            self._stream_logs(proc, name)
            return proc
        except FileNotFoundError:
            log.warning(f"[{name}] command not found: {cmd[0]} — skipping")
            return None
        except Exception as e:
            log.error(f"[{name}] failed to start: {e}")
            return None

    def _stream_logs(self, proc: subprocess.Popen, name: str):
        def reader():
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log.info(f"[{name}] {line}")
        threading.Thread(target=reader, daemon=True).start()

    def shutdown_all(self):
        log.info("Shutting down all Beacon processes...")
        with self._lock:
            for proc in self.processes:
                if proc.poll() is None:
                    proc.terminate()
            time.sleep(2)
            for proc in self.processes:
                if proc.poll() is None:
                    proc.kill()
                    log.warning(f"Force-killed PID {proc.pid}")
        log.info("All processes stopped.")

    def health_check(self) -> dict:
        """
        FIX 1: On each check, remove dead processes from the watch list.
        Log their exit once. Never see them again. No more spam.
        """
        status = {}
        with self._lock:
            alive = []
            for proc in self.processes:
                if proc.poll() is None:
                    alive.append(proc)
                    status[proc.pid] = "running"
                else:
                    log.warning(
                        f"PID {proc.pid} exited (code {proc.returncode}) — removed from watch list"
                    )
                    status[proc.pid] = f"exited ({proc.returncode})"
            self.processes = alive   # dead PIDs are gone for good
        return status

    @property
    def alive_count(self) -> int:
        with self._lock:
            return sum(1 for p in self.processes if p.poll() is None)


# ─────────────────────────────────────────────
#  MISSION REPORT
# ─────────────────────────────────────────────

class MissionReport:
    def __init__(self, scenario: str, config: BeaconConfig):
        self.scenario = scenario
        self.config = config
        self.start_time = datetime.now()
        self.events: List[dict] = []
        self.alerts: List[dict] = []

    def log_event(self, event_type: str, detail: str):
        self.events.append({
            "time": datetime.now().isoformat(),
            "type": event_type,
            "detail": detail,
        })

    def log_alert(self, severity: str, location: dict, description: str):
        self.alerts.append({
            "time": datetime.now().isoformat(),
            "severity": severity,
            "location": location,
            "description": description,
        })

    def save(self, path: str = None):
        if not path:
            ts = self.start_time.strftime("%Y%m%d_%H%M%S")
            path = f"reports/mission_{self.scenario}_{ts}.json"
        os.makedirs("reports", exist_ok=True)
        report = {
            "scenario": self.scenario,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "duration_s": (datetime.now() - self.start_time).seconds,
            "simulate_mode": self.config.simulate,
            "total_alerts": len(self.alerts),
            "alerts": self.alerts,
            "events": self.events,
        }
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        log.info(f"Mission report saved: {path}")
        return path


# ─────────────────────────────────────────────
#  BEACON LAUNCHER
# ─────────────────────────────────────────────

class BeaconLauncher:
    def __init__(self, config: BeaconConfig):
        self.config = config
        self.pm = ProcessManager()
        self.report: Optional[MissionReport] = None
        self._shutdown_event = threading.Event()

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        log.info(f"Signal {signum} received — initiating shutdown")
        self._shutdown_event.set()

    def _check_dependencies(self) -> bool:
        for dep in ["python3"]:
            if subprocess.run(["which", dep], capture_output=True).returncode != 0:
                log.error(f"Missing dependency: {dep}")
                return False
        return True

    def _launch_dashboard(self):
        if not Path("server.py").exists():
            log.warning("server.py not found — dashboard will not start")
            return
        self.pm.spawn(
            ["python3", "server.py",
             "--host", self.config.dashboard_host,
             "--port", str(self.config.dashboard_port)],
            name="dashboard",
        )
        log.info(f"Dashboard → http://{self.config.dashboard_host}:{self.config.dashboard_port}")

    def _launch_integration(self, scenario: str):
        entry = SCENARIOS[scenario]["entry"]
        if not Path(entry).exists():
            log.warning(f"{entry} not found — mission loop will not start")
            return
        env = os.environ.copy()
        env["BEACON_SCENARIO"]   = scenario
        env["BEACON_SIMULATE"]   = "1" if self.config.simulate else "0"
        env["BEACON_CONNECTION"] = self.config.drone_connection
        self.pm.spawn(["python3", "-u", entry], name="mission", env=env)

    def _launch_consensus(self, scenario: str):
        if not Path("consensus.py").exists():
            log.warning("consensus.py not found — model consensus will not start")
            return
        loc = SCENARIOS[scenario]["demo_location"]
        self.pm.spawn(
            ["python3", "consensus.py",
             "--scenario", scenario,
             "--lat", str(loc["lat"]),
             "--lon", str(loc["lon"])],
            name="consensus",
        )

    def _health_monitor(self):
        """
        FIX 1 (continued): once alive_count hits zero, stop monitoring.
        All missions are done. Log it once and exit the thread.
        """
        while not self._shutdown_event.is_set():
            time.sleep(30)
            if self.pm.alive_count == 0:
                log.info("All subprocesses have completed — Beacon idle. Press Ctrl+C to exit.")
                return
            self.pm.health_check()

    def launch(self, scenario: str, dashboard_only: bool = False):
        log.info("=" * 60)
        log.info("🔺 BEACON AUTONOMOUS DISASTER RESPONSE SYSTEM")
        log.info("=" * 60)
        log.info(f"Scenario      : {SCENARIOS[scenario]['name'] if not dashboard_only else 'Dashboard only'}")
        log.info(f"Simulate mode : {self.config.simulate}")
        log.info(f"Connection    : {self.config.drone_connection}")
        log.info(f"Log file      : {log_filename}")
        log.info("=" * 60)

        if not self._check_dependencies():
            sys.exit(1)

        if not dashboard_only:
            self.report = MissionReport(scenario, self.config)
            self.report.log_event("launch", f"Scenario: {scenario}")

        if self.config.dashboard_enabled:
            self._launch_dashboard()
            time.sleep(1.5)

        if not dashboard_only:
            self._launch_integration(scenario)
            self._launch_consensus(scenario)

        threading.Thread(target=self._health_monitor, daemon=True).start()

        log.info("Beacon is running. Press Ctrl+C to stop.")
        self._shutdown_event.wait()

        log.info("Shutting down Beacon...")
        self.pm.shutdown_all()

        if self.report and self.config.generate_report:
            self.report.log_event("shutdown", "Mission ended")
            self.report.save()

        log.info("Beacon stopped cleanly.")


# ─────────────────────────────────────────────
#  INTERACTIVE SCENARIO PICKER
# ─────────────────────────────────────────────

def interactive_select() -> str:
    print("\n🔺 BEACON — Select a scenario:\n")
    keys = list(SCENARIOS.keys())
    for i, key in enumerate(keys, 1):
        s = SCENARIOS[key]
        print(f"  [{i}] {s['name']}")
        print(f"      {s['description'][:80]}...")
        print()
    while True:
        try:
            choice = input("Enter number (or 'q' to quit): ").strip()
            if choice.lower() == "q":
                sys.exit(0)
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
            print("Invalid choice. Try again.")
        except (ValueError, KeyboardInterrupt):
            print("\nExiting.")
            sys.exit(0)


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        prog="beacon",
        description="Beacon Autonomous Disaster Response System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--scenario", "-s", choices=list(SCENARIOS.keys()),
                        help="Scenario to run")
    parser.add_argument("--simulate", action="store_true",
                        help="Simulation mode — no drone hardware required")
    parser.add_argument("--dashboard-only", action="store_true",
                        help="Launch dashboard only, no mission")
    parser.add_argument("--config", "-c", type=str, default=None,
                        help="Path to config JSON file")
    parser.add_argument("--list-scenarios", action="store_true",
                        help="Print all scenarios and exit")
    parser.add_argument("--generate-config", action="store_true",
                        help="Write default config.json and exit")
    parser.add_argument("--connection", type=str, default=None,
                        help="MAVLink connection string (e.g. udp:127.0.0.1:14550)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = BeaconConfig.from_file(args.config) if args.config else BeaconConfig()

    if args.simulate:
        config.simulate = True
    if args.connection:
        config.drone_connection = args.connection

    if args.list_scenarios:
        print("\n🔺 BEACON — Available Scenarios\n")
        for key, s in SCENARIOS.items():
            print(f"  {key:<12} {s['name']}")
            print(f"               Models : {', '.join(s['models'])}")
            print(f"               Feeds  : {', '.join(s['feeds'])}")
            print()
        sys.exit(0)

    if args.generate_config:
        config.save("config.json")
        print("config.json written.")
        sys.exit(0)

    if args.dashboard_only:
        BeaconLauncher(config).launch(scenario="wildfire", dashboard_only=True)
        return

    scenario = args.scenario or interactive_select()
    BeaconLauncher(config).launch(scenario=scenario)


if __name__ == "__main__":
    main()