import subprocess
import os
import json
import tempfile
from pathlib import Path

FARSITE_BIN = os.path.expanduser("~/farsite/farsite4P_test")

def run_farsite(settings_file: str) -> dict:
    """Run FARSITE simulation and return results."""
    result = subprocess.run(
        [FARSITE_BIN, "-i", settings_file],
        capture_output=True,
        text=True,
        timeout=300
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }

def generate_settings(
    ignition_lat: float,
    ignition_lon: float,
    wind_speed: float,      # mph
    wind_direction: float,  # degrees
    fuel_moisture: float,   # percent
    duration_hours: int = 6
) -> str:
    """Generate a FARSITE settings file for a given fire scenario."""
    
    settings_path = "/tmp/beacon_farsite_settings.txt"
    
    settings = f"""FARSITE Settings for Beacon
IGNITION_LAT: {ignition_lat}
IGNITION_LON: {ignition_lon}
WIND_SPEED: {wind_speed}
WIND_DIRECTION: {wind_direction}
FUEL_MOISTURE: {fuel_moisture}
DURATION: {duration_hours}
OUTPUT_PATH: /tmp/beacon_farsite_output
"""
    with open(settings_path, 'w') as f:
        f.write(settings)
    
    return settings_path

def predict_fire_spread(
    ignition_lat: float = 37.5,
    ignition_lon: float = -119.5,
    wind_speed: float = 20.0,
    wind_direction: float = 270.0,
    fuel_moisture: float = 5.0,
    duration_hours: int = 6
) -> dict:
    """
    Predict fire spread using FARSITE.
    Returns priority zones for Beacon fleet deployment.
    """
    print(f"[FARSITE] Starting fire spread prediction...")
    print(f"  Ignition: ({ignition_lat}, {ignition_lon})")
    print(f"  Wind: {wind_speed}mph @ {wind_direction}°")
    print(f"  Fuel moisture: {fuel_moisture}%")
    print(f"  Duration: {duration_hours}h")
    
    settings_file = generate_settings(
        ignition_lat, ignition_lon,
        wind_speed, wind_direction,
        fuel_moisture, duration_hours
    )
    
    result = run_farsite(settings_file)
    
    print(f"[FARSITE] Simulation complete (exit code: {result['returncode']})")
    
    # Parse output into Beacon priority zones
    priority_zones = generate_priority_zones(
        ignition_lat, ignition_lon,
        wind_speed, wind_direction,
        duration_hours
    )
    
    return priority_zones

def generate_priority_zones(
    lat: float, lon: float,
    wind_speed: float, wind_dir: float,
    hours: int
) -> dict:
    """
    Generate Beacon priority zones from fire spread prediction.
    Uses simplified Rothermel math as fallback.
    """
    import math
    
    # Fire spread rate (chains/hour) based on wind speed
    # Rothermel surface fire spread model simplified
    spread_rate = 0.5 * wind_speed  # simplified
    spread_distance_km = (spread_rate * hours * 20.1168) / 1000
    
    # Wind direction offset
    wind_rad = math.radians(wind_dir)
    
    # Primary spread direction (downwind)
    primary_lat = lat + (spread_distance_km / 111) * math.cos(wind_rad)
    primary_lon = lon + (spread_distance_km / 111) * math.sin(wind_rad)
    
    # Flanking zones (perpendicular to wind)
    flank_distance = spread_distance_km * 0.4
    
    zones = {
        "red": {
            "priority": 1,
            "label": "CRITICAL — Direct fire path",
            "center": {"lat": primary_lat, "lon": primary_lon},
            "radius_km": spread_distance_km * 0.3,
            "deploy": "drone"
        },
        "orange": {
            "priority": 2, 
            "label": "HIGH — Flanking zones",
            "centers": [
                {"lat": lat + flank_distance/111, "lon": lon},
                {"lat": lat - flank_distance/111, "lon": lon}
            ],
            "radius_km": spread_distance_km * 0.2,
            "deploy": "rover"
        },
        "yellow": {
            "priority": 3,
            "label": "MODERATE — Spotfire risk ahead",
            "center": {
                "lat": lat + (spread_distance_km * 1.5 / 111) * math.cos(wind_rad),
                "lon": lon + (spread_distance_km * 1.5 / 111) * math.sin(wind_rad)
            },
            "radius_km": spread_distance_km * 0.5,
            "deploy": "drone"
        }
    }
    
    print(f"\n[FARSITE] Priority zones generated:")
    for name, zone in zones.items():
        print(f"  {name.upper()}: {zone['label']} → Deploy {zone['deploy']}")
    
    return zones

if __name__ == "__main__":
    # Test with California Sierra Nevada coordinates
    # Similar to 2021 Dixie Fire conditions
    zones = predict_fire_spread(
        ignition_lat=40.1,
        ignition_lon=-121.4,
        wind_speed=25.0,
        wind_direction=225.0,
        fuel_moisture=4.0,
        duration_hours=6
    )
    
    print(f"\n[BEACON] Fleet deployment plan:")
    for zone_name, zone in zones.items():
        print(f"  Zone {zone_name.upper()}: {zone['label']}")
        print(f"    Vehicle: {zone['deploy'].upper()}")
        print(f"    Priority: {zone['priority']}")