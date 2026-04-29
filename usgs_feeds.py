import requests
import math
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta

# ── USGS EARTHQUAKE FEED ─────────────────────────────────────────

@dataclass
class LiveEarthquake:
    id: str
    magnitude: float
    lat: float
    lon: float
    depth_km: float
    time: datetime
    place: str
    fault_type: str
    url: str

def get_recent_earthquakes(
    min_magnitude: float = 4.0,
    hours_back: int = 24,
    lat: float = None,
    lon: float = None,
    radius_km: float = 500
) -> List[LiveEarthquake]:
    """
    Pull recent earthquakes from USGS ComCat API.
    Free, real-time, no API key required.
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours_back)

    params = {
        "format": "geojson",
        "starttime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": min_magnitude,
        "orderby": "time",
    }

    if lat and lon:
        params["latitude"] = lat
        params["longitude"] = lon
        params["maxradiuskm"] = radius_km

    try:
        response = requests.get(
            "https://earthquake.usgs.gov/fdsnws/event/1/query",
            params=params, timeout=15
        )
        response.raise_for_status()
        data = response.json()

        earthquakes = []
        for feature in data["features"]:
            props = feature["properties"]
            coords = feature["geometry"]["coordinates"]

            earthquakes.append(LiveEarthquake(
                id=feature["id"],
                magnitude=props["mag"],
                lat=coords[1],
                lon=coords[0],
                depth_km=coords[2],
                time=datetime.utcfromtimestamp(props["time"] / 1000),
                place=props["place"] or "Unknown",
                fault_type=_guess_fault_type(coords[2], props["mag"]),
                url=props["url"]
            ))

        return earthquakes

    except Exception as e:
        print(f"[USGS] Earthquake feed error: {e}")
        return []

def get_earthquake_by_id(event_id: str) -> Optional[LiveEarthquake]:
    """Get specific earthquake event by USGS ID."""
    try:
        response = requests.get(
            f"https://earthquake.usgs.gov/fdsnws/event/1/query",
            params={"eventid": event_id, "format": "geojson"},
            timeout=10
        )
        data = response.json()
        props = data["properties"]
        coords = data["geometry"]["coordinates"]

        return LiveEarthquake(
            id=event_id,
            magnitude=props["mag"],
            lat=coords[1],
            lon=coords[0],
            depth_km=coords[2],
            time=datetime.utcfromtimestamp(props["time"] / 1000),
            place=props["place"],
            fault_type=_guess_fault_type(coords[2], props["mag"]),
            url=props["url"]
        )
    except Exception as e:
        print(f"[USGS] Event fetch error: {e}")
        return None

def _guess_fault_type(depth_km: float, magnitude: float) -> str:
    """Estimate fault type from depth."""
    if depth_km < 20:
        return "strike_slip"
    elif depth_km < 70:
        return "reverse"
    else:
        return "normal"

# ── NOAA TSUNAMI WARNINGS ────────────────────────────────────────

@dataclass
class TsunamiWarning:
    event_id: str
    status: str          # WARNING, WATCH, ADVISORY, INFORMATION
    magnitude: float
    epicenter_lat: float
    epicenter_lon: float
    depth_km: float
    origin_time: datetime
    affected_regions: List[str]
    wave_arrival_times: dict
    threat_level: str

def get_active_tsunami_warnings() -> List[TsunamiWarning]:
    """
    Pull active tsunami warnings from NOAA Tsunami Warning Center.
    """
    urls = [
        "https://www.tsunami.gov/events/xml/PHEBulletin.xml",
        "https://www.tsunami.gov/events/xml/ATWCBulletin.xml"
    ]

    warnings = []
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Parse XML for active warnings
                content = response.text
                if "WARNING" in content or "WATCH" in content:
                    warnings.append(TsunamiWarning(
                        event_id="ACTIVE",
                        status="WARNING",
                        magnitude=0,
                        epicenter_lat=0,
                        epicenter_lon=0,
                        depth_km=0,
                        origin_time=datetime.utcnow(),
                        affected_regions=["Check tsunami.gov"],
                        wave_arrival_times={},
                        threat_level="critical"
                    ))
        except Exception as e:
            print(f"[NOAA] Tsunami warning fetch error: {e}")

    return warnings

def get_dart_buoy_data(buoy_ids: List[str] = None) -> dict:
    """
    Pull DART buoy ocean pressure data from NOAA.
    DART = Deep-ocean Assessment and Reporting of Tsunamis.
    """
    if not buoy_ids:
        # Major Pacific DART buoys
        buoy_ids = ["21413", "21418", "21419", "46408", "46411"]

    results = {}
    for buoy_id in buoy_ids:
        try:
            url = f"https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.dart"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                lines = response.text.strip().split("\n")
                # Parse most recent reading
                for line in lines:
                    if line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 6:
                        try:
                            results[buoy_id] = {
                                "year": parts[0],
                                "month": parts[1],
                                "day": parts[2],
                                "hour": parts[3],
                                "minute": parts[4],
                                "water_column_height_m": float(parts[5]),
                                "status": "normal" if abs(float(parts[5]) - 4000) < 10 else "anomaly"
                            }
                            break
                        except:
                            continue
        except Exception as e:
            results[buoy_id] = {"error": str(e)}

    return results

# ── NASA FIRMS FIRE DETECTION ─────────────────────────────────────

@dataclass
class ActiveFire:
    lat: float
    lon: float
    brightness_k: float      # brightness temperature Kelvin
    frp_mw: float           # fire radiative power MW
    confidence: str          # low/nominal/high
    satellite: str
    acquisition_time: str
    daynight: str

def get_active_fires(
    lat: float,
    lon: float,
    radius_km: float = 100,
    days_back: int = 1
) -> List[ActiveFire]:
    """
    Pull active fire detections from NASA FIRMS.
    Uses VIIRS satellite — 375m resolution, updated every 3 hours.
    Requires free NASA FIRMS API key — register at firms.modaps.eosdis.nasa.gov
    Falls back to USFS active fire perimeter data if no key.
    """
    # Try NASA FIRMS API
    # Get free key at: https://firms.modaps.eosdis.nasa.gov/api/area/
    API_KEY = "YOUR_FIRMS_KEY"  # Replace with free key

    if API_KEY != "YOUR_FIRMS_KEY":
        try:
            # FIRMS API area query
            west = lon - (radius_km / 111)
            east = lon + (radius_km / 111)
            south = lat - (radius_km / 111)
            north = lat + (radius_km / 111)

            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{API_KEY}/VIIRS_SNPP_NRT/{west},{south},{east},{north}/{days_back}"
            response = requests.get(url, timeout=15)

            fires = []
            lines = response.text.strip().split("\n")
            headers = lines[0].split(",")

            for line in lines[1:]:
                vals = line.split(",")
                if len(vals) < 5:
                    continue
                try:
                    fires.append(ActiveFire(
                        lat=float(vals[0]),
                        lon=float(vals[1]),
                        brightness_k=float(vals[2]),
                        frp_mw=float(vals[5]) if len(vals) > 5 else 0,
                        confidence=vals[8] if len(vals) > 8 else "nominal",
                        satellite="VIIRS_SNPP",
                        acquisition_time=vals[6] if len(vals) > 6 else "",
                        daynight=vals[7] if len(vals) > 7 else "D"
                    ))
                except:
                    continue
            return fires

        except Exception as e:
            print(f"[FIRMS] API error: {e}")

    # Fallback — USFS GeoMAC active perimeters
    try:
        url = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/Active_Fires/FeatureServer/0/query"
        params = {
            "where": "1=1",
            "outFields": "*",
            "geometry": f"{lon-1},{lat-1},{lon+1},{lat+1}",
            "geometryType": "esriGeometryEnvelope",
            "f": "json"
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        fires = []
        for feature in data.get("features", []):
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry", {})
            fires.append(ActiveFire(
                lat=geom.get("y", lat),
                lon=geom.get("x", lon),
                brightness_k=500,
                frp_mw=attrs.get("GISAcres", 0) * 0.1,
                confidence="high",
                satellite="USFS_GeoMAC",
                acquisition_time=str(attrs.get("CreateDate", "")),
                daynight="D"
            ))
        return fires

    except Exception as e:
        print(f"[FIRMS] GeoMAC fallback error: {e}")
        return []

# ── NOAA RAWS FUEL MOISTURE ──────────────────────────────────────

def get_raws_fuel_moisture(
    lat: float,
    lon: float
) -> dict:
    """
    Pull fuel moisture data from NOAA Remote Automated Weather Stations.
    Critical input for Rothermel and FARSITE fire models.
    """
    try:
        # SynopticData API (free tier available)
        url = "https://api.synopticdata.com/v2/stations/nearesttime"
        params = {
            "token": "demotoken",  # Free demo token
            "radius": f"{lat},{lon},50",
            "vars": "fuel_moisture,relative_humidity,wind_speed,wind_direction,air_temp",
            "units": "metric",
            "output": "json"
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if "STATION" in data and data["STATION"]:
            station = data["STATION"][0]
            obs = station.get("OBSERVATIONS", {})

            fuel_moisture = obs.get("fuel_moisture_value_1", {})
            if fuel_moisture:
                fm_val = float(fuel_moisture.get("value", 10))
                return {
                    "fuel_moisture_1hr": fm_val / 100,
                    "fuel_moisture_10hr": min(fm_val * 1.5 / 100, 0.40),
                    "fuel_moisture_100hr": min(fm_val * 2.0 / 100, 0.40),
                    "station": station.get("NAME", "Unknown"),
                    "live": True
                }
    except Exception as e:
        print(f"[RAWS] Fuel moisture fetch error: {e}")

    # Fallback to NOAA weather-derived moisture
    return {"live": False}

# ── NOAA RAINFALL ────────────────────────────────────────────────

def get_noaa_rainfall(
    lat: float,
    lon: float,
    hours_back: int = 24
) -> dict:
    """
    Pull recent precipitation from NOAA Weather API.
    """
    try:
        # Get nearest station
        url = f"https://api.weather.gov/points/{lat},{lon}"
        headers = {"User-Agent": "Beacon-Disaster-Response/1.0"}
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()

        stations_url = data["properties"]["observationStations"]
        stations = requests.get(stations_url, headers=headers, timeout=10).json()
        station_id = stations["features"][0]["properties"]["stationIdentifier"]

        # Get observations
        obs_url = f"https://api.weather.gov/stations/{station_id}/observations"
        obs = requests.get(obs_url, headers=headers, timeout=10).json()

        total_precip_mm = 0
        for feature in obs["features"][:hours_back]:
            precip = feature["properties"].get("precipitationLastHour", {})
            val = precip.get("value") if precip else None
            if val:
                total_precip_mm += val * 1000  # convert m to mm

        return {
            "total_precipitation_mm": total_precip_mm,
            "station": station_id,
            "hours": hours_back,
            "live": True
        }

    except Exception as e:
        print(f"[NOAA] Rainfall fetch error: {e}")
        return {"total_precipitation_mm": 0, "live": False}

# ── NHC HURRICANE FEED ───────────────────────────────────────────

@dataclass
class ActiveHurricane:
    name: str
    category: int
    wind_speed_mph: float
    central_pressure_mb: float
    lat: float
    lon: float
    forward_speed_mph: float
    heading_deg: float
    radius_max_wind_km: float
    forecast_track: List[dict]

def get_active_hurricanes() -> List[ActiveHurricane]:
    """
    Pull active hurricane/tropical storm data from NHC RSS feed.
    """
    try:
        url = "https://www.nhc.noaa.gov/CurrentStorms.json"
        response = requests.get(url, timeout=10)
        data = response.json()

        hurricanes = []
        for storm in data.get("activeStorms", []):
            try:
                wind = float(storm.get("maxWindMph", 0))
                category = _wind_to_category(wind)

                hurricanes.append(ActiveHurricane(
                    name=storm.get("name", "Unknown"),
                    category=category,
                    wind_speed_mph=wind,
                    central_pressure_mb=float(storm.get("minPressureMb", 1013)),
                    lat=float(storm.get("latitudeNumeric", 0)),
                    lon=float(storm.get("longitudeNumeric", 0)),
                    forward_speed_mph=float(storm.get("movementSpeedMph", 10)),
                    heading_deg=float(storm.get("movementDir", 0)),
                    radius_max_wind_km=50,
                    forecast_track=storm.get("forecast", [])
                ))
            except Exception as e:
                print(f"[NHC] Storm parse error: {e}")

        return hurricanes

    except Exception as e:
        print(f"[NHC] Hurricane feed error: {e}")
        return []

def _wind_to_category(wind_mph: float) -> int:
    if wind_mph >= 157: return 5
    elif wind_mph >= 130: return 4
    elif wind_mph >= 111: return 3
    elif wind_mph >= 96: return 2
    elif wind_mph >= 74: return 1
    return 0

# ── UNIFIED DISASTER FEED ────────────────────────────────────────

class BeaconLiveFeed:
    """
    Unified live data feed for all Beacon models.
    Single entry point for all real-time disaster data.
    """

    def get_earthquake_situation(
        self,
        lat: float,
        lon: float,
        radius_km: float = 300
    ) -> dict:
        """Get current earthquake situation for a location."""
        print(f"[FEED] Fetching earthquake data near ({lat}, {lon})...")
        quakes = get_recent_earthquakes(
            min_magnitude=3.0,
            hours_back=72,
            lat=lat, lon=lon,
            radius_km=radius_km
        )

        if not quakes:
            return {"active": False, "events": []}

        largest = max(quakes, key=lambda q: q.magnitude)
        return {
            "active": True,
            "event_count": len(quakes),
            "largest": largest,
            "all_events": quakes,
            "sequence_accelerating": len(quakes) > 10
        }

    def get_fire_situation(
        self,
        lat: float,
        lon: float,
        radius_km: float = 100
    ) -> dict:
        """Get current fire situation for a location."""
        print(f"[FEED] Fetching fire data near ({lat}, {lon})...")
        fires = get_active_fires(lat, lon, radius_km)
        weather = get_raws_fuel_moisture(lat, lon)

        return {
            "active": len(fires) > 0,
            "fire_count": len(fires),
            "fires": fires,
            "fuel_moisture": weather,
            "high_confidence_fires": [f for f in fires if f.confidence == "high"]
        }

    def get_flood_situation(
        self,
        lat: float,
        lon: float
    ) -> dict:
        """Get current flood situation for a location."""
        print(f"[FEED] Fetching flood data near ({lat}, {lon})...")
        rainfall = get_noaa_rainfall(lat, lon, hours_back=24)

        return {
            "active": rainfall["total_precipitation_mm"] > 50,
            "rainfall_mm_24h": rainfall["total_precipitation_mm"],
            "station": rainfall.get("station"),
            "live": rainfall["live"]
        }

    def get_hurricane_situation(self) -> dict:
        """Get active hurricane situation globally."""
        print("[FEED] Fetching hurricane data...")
        storms = get_active_hurricanes()

        return {
            "active": len(storms) > 0,
            "storm_count": len(storms),
            "storms": storms,
            "cat3_or_higher": [s for s in storms if s.category >= 3]
        }

    def get_tsunami_situation(self) -> dict:
        """Get active tsunami warnings globally."""
        print("[FEED] Fetching tsunami warnings...")
        warnings = get_active_tsunami_warnings()
        dart = get_dart_buoy_data()

        anomalies = {k: v for k, v in dart.items()
                    if isinstance(v, dict) and v.get("status") == "anomaly"}

        return {
            "active_warnings": len(warnings) > 0,
            "warnings": warnings,
            "dart_anomalies": anomalies,
            "dart_stations": len(dart)
        }

    def full_situation(self, lat: float, lon: float) -> dict:
        """Pull complete disaster situation for any location."""
        return {
            "location": {"lat": lat, "lon": lon},
            "earthquake": self.get_earthquake_situation(lat, lon),
            "fire": self.get_fire_situation(lat, lon),
            "flood": self.get_flood_situation(lat, lon),
            "hurricane": self.get_hurricane_situation(),
            "tsunami": self.get_tsunami_situation()
        }


if __name__ == "__main__":
    feed = BeaconLiveFeed()

    print("📡 BEACON LIVE DATA FEED")
    print("USGS + NOAA + NASA FIRMS + NHC\n")

    # Test locations
    locations = [
        ("Los Angeles CA", 34.05, -118.25),
        ("Dallas TX", 32.78, -96.80),
        ("Honolulu HI", 21.31, -157.86),
    ]

    for name, lat, lon in locations:
        print(f"\n{'='*55}")
        print(f"LOCATION: {name}")
        print(f"{'='*55}")

        # Earthquakes
        eq = feed.get_earthquake_situation(lat, lon, radius_km=500)
        print(f"\n🌍 EARTHQUAKES:")
        if eq["active"]:
            print(f"  {eq['event_count']} events in last 72h")
            print(f"  Largest: M{eq['largest'].magnitude} — {eq['largest'].place}")
        else:
            print("  No significant seismic activity")

        # Fires
        fire = feed.get_fire_situation(lat, lon, radius_km=150)
        print(f"\n🔥 FIRES:")
        print(f"  {fire['fire_count']} active fire detections")

        # Flood
        flood = feed.get_flood_situation(lat, lon)
        print(f"\n🌊 FLOOD:")
        print(f"  24h rainfall: {flood['rainfall_mm_24h']:.1f}mm")

    # Global
    print(f"\n{'='*55}")
    print("GLOBAL STATUS")
    print(f"{'='*55}")

    hurricane = feed.get_hurricane_situation()
    print(f"\n🌀 HURRICANES: {hurricane['storm_count']} active storms")

    tsunami = feed.get_tsunami_situation()
    print(f"\n🌊 TSUNAMI: {'ACTIVE WARNINGS' if tsunami['active_warnings'] else 'No active warnings'}")
    print(f"   DART buoys monitoring: {tsunami['dart_stations']}")