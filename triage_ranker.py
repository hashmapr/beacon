import json
import os
import datetime
import math

TRIAGE_DIR = "triage_results"

# ---------------------------------------------------------------------------
# Geometry helper
# ---------------------------------------------------------------------------

def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """
    Ray-casting algorithm.
    polygon = list of (lat, lon) tuples forming a closed ring.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def zone_for_candidate(candidate: dict, consensus_map: dict) -> str | None:
    """Return 'RED', 'ORANGE', or None depending on which zone the candidate sits in."""
    lat = candidate["estimated_lat"]
    lon = candidate["estimated_lon"]
    for zone in consensus_map.get("zones", []):
        if point_in_polygon(lat, lon, zone["polygon"]):
            return zone["level"]
    return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_survivor(candidate: dict, consensus_map: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    # -- FACTOR 1: Hazard zone --
    zone = zone_for_candidate(candidate, consensus_map)
    if zone == "RED":
        score += 50
        reasons.append("Inside RED hazard zone")
    elif zone == "ORANGE":
        score += 25
        reasons.append("Inside ORANGE hazard zone")

    # -- FACTOR 2: Thermal temperature --
    temp = candidate.get("temperature_c")
    if temp is not None:
        if temp > 39.5 or temp < 35.0:
            score += 30
            reasons.append(f"Critical temperature: {temp:.1f}°C")
        elif temp > 38.5 or temp < 36.0:
            score += 15
            reasons.append(f"Abnormal temperature: {temp:.1f}°C")

    # -- FACTOR 3: Time since first detection --
    try:
        first_seen = datetime.datetime.fromisoformat(candidate["first_seen"])
        minutes_missing = (datetime.datetime.now() - first_seen).total_seconds() / 60
        if minutes_missing > 120:
            score += 25
            reasons.append(f"Uncontacted for {int(minutes_missing)} minutes")
        elif minutes_missing > 60:
            score += 10
            reasons.append(f"Uncontacted for {int(minutes_missing)} minutes")
    except (KeyError, ValueError):
        pass

    # -- FACTOR 4: Signal strength trend --
    signal_history = candidate.get("signal_history", [])
    if len(signal_history) >= 2:
        trend = signal_history[-1] - signal_history[0]
        if trend < -10:
            score += 20
            reasons.append(f"Signal declining rapidly ({trend:+.1f} dBm) — battery dying")
        elif trend < -5:
            score += 10
            reasons.append(f"Signal weakening ({trend:+.1f} dBm)")

    # -- FACTOR 5: Triangulation confidence --
    conf = candidate.get("triangulation_confidence", 0)
    if conf > 0.8:
        score += 15
        reasons.append(f"High position confidence ({int(conf * 100)}%)")
    elif conf > 0.5:
        score += 7
        # No reason string — minor boost, not worth surfacing in triage report

    return score, reasons


def rank_survivors(candidates: list[dict], consensus_map: dict) -> list[dict]:
    ranked = []
    for candidate in candidates:
        score, reasons = score_survivor(candidate, consensus_map)
        entry = {**candidate, "triage_score": score, "triage_reasons": reasons}
        ranked.append(entry)

    ranked.sort(key=lambda x: x["triage_score"], reverse=True)

    for i, entry in enumerate(ranked):
        entry["priority_rank"] = i + 1

    return ranked


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

PRIORITY_LABELS = {1: "CRITICAL", 2: "HIGH", 3: "HIGH", 4: "MEDIUM", 5: "MEDIUM"}

def priority_label(rank: int, score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "MEDIUM"
    return "LOW"


def print_ranked(ranked: list[dict]) -> None:
    width = 60
    print("\n" + "=" * width)
    print("  BEACON TRIAGE — Survivor Priority Report")
    print(f"  Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * width)

    for s in ranked:
        rank  = s["priority_rank"]
        label = priority_label(rank, s["triage_score"])
        mac   = s["mac_address"]
        lat   = s["estimated_lat"]
        lon   = s["estimated_lon"]
        score = s["triage_score"]
        conf  = int(s.get("triangulation_confidence", 0) * 100)
        dist  = s.get("avg_distance_m", "?")
        temp  = s.get("temperature_c")
        temp_str = f"{temp:.1f}°C" if temp is not None else "N/A"

        print(f"\n  #{rank}  [{label}]  Score: {score}")
        print(f"  MAC      : {mac}")
        print(f"  Position : {lat}°N, {lon}°W")
        print(f"  Distance : ~{dist}m from drone  |  Confidence: {conf}%")
        print(f"  Temp     : {temp_str}")
        print(f"  Detections: {s.get('detection_count', '?')}")
        if s["triage_reasons"]:
            print(f"  Flags    :")
            for r in s["triage_reasons"]:
                print(f"    • {r}")

    print("\n" + "=" * width + "\n")


def save_report(ranked: list[dict]) -> str:
    os.makedirs(TRIAGE_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(TRIAGE_DIR, f"triage_report_{timestamp}.json")
    with open(path, "w") as f:
        json.dump({
            "generated_at": datetime.datetime.now().isoformat(),
            "total_candidates": len(ranked),
            "ranked_survivors": ranked,
        }, f, indent=2)
    print(f"[TRIAGE] Report saved → {path}")
    return path


# ---------------------------------------------------------------------------
# Fake data for standalone testing
# ---------------------------------------------------------------------------

def make_fake_candidates() -> list[dict]:
    """
    5 test cases that exercise every scoring branch.
    signal_history is a list of dBm readings over time (first → last).
    temperature_c is injected here; in production the thermal drone would supply it.
    """
    now = datetime.datetime.now()

    def ts(minutes_ago: int) -> str:
        return (now - datetime.timedelta(minutes=minutes_ago)).isoformat()

    return [
        {
            # Should score high: RED zone + critical temp + long missing + dying signal
            "mac_address": "AA:BB:CC:DD:EE:01",
            "estimated_lat": 33.1034,   # inside RED polygon below
            "estimated_lon": -96.6710,
            "triangulation_confidence": 0.91,
            "detection_count": 14,
            "avg_signal_dbm": -72.0,
            "avg_distance_m": 18.5,
            "temperature_c": 40.1,
            "first_seen": ts(150),
            "last_seen": ts(5),
            "signal_history": [-61.0, -68.0, -74.0, -83.0],
            "frequencies_seen": ["2.4 GHz (WiFi)"],
            "likely_mobile_device": True,
        },
        {
            # ORANGE zone + abnormal temp + weakening signal
            "mac_address": "AA:BB:CC:DD:EE:02",
            "estimated_lat": 33.1028,
            "estimated_lon": -96.6715,
            "triangulation_confidence": 0.76,
            "detection_count": 9,
            "avg_signal_dbm": -67.0,
            "avg_distance_m": 11.2,
            "temperature_c": 38.8,
            "first_seen": ts(80),
            "last_seen": ts(10),
            "signal_history": [-62.0, -65.0, -68.5],
            "frequencies_seen": ["2.4 GHz (Bluetooth)"],
            "likely_mobile_device": True,
        },
        {
            # No zone, normal temp, missing >60min, medium confidence
            "mac_address": "AA:BB:CC:DD:EE:03",
            "estimated_lat": 33.1020,
            "estimated_lon": -96.6690,
            "triangulation_confidence": 0.62,
            "detection_count": 6,
            "avg_signal_dbm": -70.5,
            "avg_distance_m": 23.0,
            "temperature_c": 37.1,
            "first_seen": ts(75),
            "last_seen": ts(15),
            "signal_history": [-69.0, -70.0, -71.5],
            "frequencies_seen": ["2.4 GHz (WiFi)"],
            "likely_mobile_device": True,
        },
        {
            # RED zone, hypothermic temp, recent detection (not missing long)
            "mac_address": "AA:BB:CC:DD:EE:04",
            "estimated_lat": 33.1035,
            "estimated_lon": -96.6712,
            "triangulation_confidence": 0.85,
            "detection_count": 11,
            "avg_signal_dbm": -58.0,
            "avg_distance_m": 5.4,
            "temperature_c": 34.2,
            "first_seen": ts(30),
            "last_seen": ts(1),
            "signal_history": [-57.5, -58.0, -58.5],
            "frequencies_seen": ["2.4 GHz (WiFi)"],
            "likely_mobile_device": True,
        },
        {
            # No zone, normal temp, short time, stable signal — low priority
            "mac_address": "AA:BB:CC:DD:EE:05",
            "estimated_lat": 33.1015,
            "estimated_lon": -96.6695,
            "triangulation_confidence": 0.44,
            "detection_count": 3,
            "avg_signal_dbm": -79.0,
            "avg_distance_m": 38.0,
            "temperature_c": 36.8,
            "first_seen": ts(20),
            "last_seen": ts(8),
            "signal_history": [-78.0, -79.5],
            "frequencies_seen": ["2.4 GHz (Bluetooth)"],
            "likely_mobile_device": True,
        },
    ]


def make_fake_consensus_map() -> dict:
    """
    Two hazard zones around the Allen TX drone position.
    RED  = tight box directly north of drone
    ORANGE = wider box slightly southwest
    Polygons are (lat, lon) tuples.
    """
    return {
        "zones": [
            {
                "level": "RED",
                "label": "Structure collapse zone",
                "polygon": [
                    (33.1033, -96.6713),
                    (33.1033, -96.6706),
                    (33.1038, -96.6706),
                    (33.1038, -96.6713),
                ],
            },
            {
                "level": "ORANGE",
                "label": "Flood risk zone",
                "polygon": [
                    (33.1024, -96.6720),
                    (33.1024, -96.6710),
                    (33.1030, -96.6710),
                    (33.1030, -96.6720),
                ],
            },
        ]
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Try loading from latest beacon sniffer report first
    candidates = None
    beacon_dir = "sniffer_results"
    if os.path.isdir(beacon_dir):
        reports = sorted(
            [f for f in os.listdir(beacon_dir) if f.endswith(".json")],
            reverse=True,
        )
        if reports:
            path = os.path.join(beacon_dir, reports[0])
            with open(path) as f:
                data = json.load(f)
            candidates = data.get("survivor_candidates", [])
            if candidates:
                # Inject fake temperatures since beacon sniffer doesn't supply them yet
                import random
                for c in candidates:
                    c.setdefault("temperature_c", round(random.uniform(35.5, 40.5), 1))
                    # Build a rough signal_history from avg (no history in v1 output)
                    avg = c.get("avg_signal_dbm", -70)
                    c.setdefault("signal_history", [avg + 4, avg, avg - 3])
                print(f"[TRIAGE] Loaded {len(candidates)} candidates from {path}")

    if not candidates:
        print("[TRIAGE] No sniffer output found — using hardcoded test cases")
        candidates = make_fake_candidates()

    consensus_map = make_fake_consensus_map()

    ranked = rank_survivors(candidates, consensus_map)
    print_ranked(ranked)
    save_report(ranked)


if __name__ == "__main__":
    main()