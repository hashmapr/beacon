import math
import requests
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


# ── LIVE NHC HURRICANE FEED ──────────────────────────────────────

def get_active_hurricanes() -> list:
    """Pull active storms from NOAA NHC JSON feed."""
    try:
        r = requests.get("https://www.nhc.noaa.gov/CurrentStorms.json", timeout=10)
        r.raise_for_status()
        storms = r.json().get("activeStorms", [])
        result = []
        for s in storms:
            wind = float(s.get("maxWindMph", 0) or 0)
            result.append({
                "name":          s.get("name", "Unknown"),
                "category":      _wind_to_category(wind),
                "wind_mph":      wind,
                "pressure_mb":   float(s.get("minPressureMb", 1013) or 1013),
                "lat":           float(s.get("latitudeNumeric", 0) or 0),
                "lon":           float(s.get("longitudeNumeric", 0) or 0),
                "forward_mph":   float(s.get("movementSpeedMph", 10) or 10),
                "heading_deg":   float(s.get("movementDir", 0) or 0),
                "basin":         s.get("basin", ""),
                "live":          True
            })
        print(f"[NHC] {len(result)} active storm(s) found")
        return result
    except Exception as e:
        print(f"[NHC] Storm feed error: {e}")
        return []


def get_nhc_forecast_track(storm_id: str) -> list:
    """Pull NHC forecast track for a specific storm."""
    try:
        url = f"https://www.nhc.noaa.gov/gis/forecast/archive/{storm_id}_5day_pgn.json"
        r   = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json().get("features", [])
    except:
        pass
    return []


def _wind_to_category(wind_mph: float) -> int:
    if wind_mph >= 157: return 5
    elif wind_mph >= 130: return 4
    elif wind_mph >= 111: return 3
    elif wind_mph >= 96:  return 2
    elif wind_mph >= 74:  return 1
    return 0


# ── SLOSH MODEL ──────────────────────────────────────────────────

class HurricaneCategory(Enum):
    TROPICAL_STORM = 0
    CAT1 = 1
    CAT2 = 2
    CAT3 = 3
    CAT4 = 4
    CAT5 = 5


@dataclass
class Hurricane:
    name: str
    category: HurricaneCategory
    wind_speed_mph: float
    central_pressure_mb: float
    radius_max_wind_km: float
    forward_speed_mph: float
    heading_deg: float
    landfall_lat: float
    landfall_lon: float
    live: bool = False

    @classmethod
    def from_live(cls, storm: dict) -> "Hurricane":
        return cls(
            name=storm["name"],
            category=HurricaneCategory(storm["category"]),
            wind_speed_mph=storm["wind_mph"],
            central_pressure_mb=storm["pressure_mb"],
            radius_max_wind_km=50,
            forward_speed_mph=storm["forward_mph"],
            heading_deg=storm["heading_deg"],
            landfall_lat=storm["lat"],
            landfall_lon=storm["lon"],
            live=True
        )


@dataclass
class CoastalPoint:
    name: str
    lat: float
    lon: float
    distance_from_landfall_km: float
    coastal_bathymetry_m: float
    inland_elevation_m: float
    population: int
    has_seawall: bool = False
    seawall_height_m: float = 0.0


@dataclass
class SLOSHResult:
    point: CoastalPoint
    hurricane: Hurricane
    surge_height_m: float
    inundation_depth_m: float
    inundation_distance_m: float
    arrival_time_min: float
    threat_level: str
    people_at_risk: int
    evacuation_zone: str

    def summary(self):
        source = "LIVE NHC" if self.hurricane.live else "Manual"
        return (
            f"Storm:             {self.hurricane.name} Cat{self.hurricane.category.value} [{source}]\n"
            f"Surge Height:      {self.surge_height_m:.1f}m\n"
            f"Inundation Depth:  {self.inundation_depth_m:.1f}m\n"
            f"Inundation Dist:   {self.inundation_distance_m:.0f}m inland\n"
            f"Arrival Time:      {self.arrival_time_min:.0f}min before landfall\n"
            f"People at Risk:    {self.people_at_risk:,}\n"
            f"Evacuation Zone:   {self.evacuation_zone}\n"
            f"Threat Level:      {self.threat_level.upper()}"
        )


CATEGORY_SURGE = {
    HurricaneCategory.TROPICAL_STORM: (0.3, 0.9),
    HurricaneCategory.CAT1:           (1.2, 1.5),
    HurricaneCategory.CAT2:           (1.8, 2.4),
    HurricaneCategory.CAT3:           (2.7, 3.7),
    HurricaneCategory.CAT4:           (4.0, 5.5),
    HurricaneCategory.CAT5:           (5.5, 8.5),
}


class SLOSHModel:
    """
    NOAA SLOSH — Sea, Lake, and Overland Surges from Hurricanes.
    Automatically pulls active storm data from NHC.

    Reference: Jelesnianski et al. 1992. NOAA Technical Report NWS 48.
    """

    def _surge_at_landfall(self, hurricane: Hurricane) -> float:
        delta_p      = max(0, 1013 - hurricane.central_pressure_mb)
        surge_p      = 0.0155 * delta_p
        surge_w      = (hurricane.wind_speed_mph / 100)**2 * 3.0
        surge_fwd    = hurricane.forward_speed_mph * 0.02
        rmw_factor   = math.exp(-hurricane.radius_max_wind_km / 50)
        total        = (surge_p + surge_w + surge_fwd) * (1 + rmw_factor)
        surge_range  = CATEGORY_SURGE.get(hurricane.category, (0, 10))
        return max(surge_range[0], min(total, surge_range[1] * 1.2))

    def _surge_at_distance(self, landfall_surge: float, dist_km: float,
                           hurricane: Hurricane) -> float:
        rmw = hurricane.radius_max_wind_km
        if dist_km <= rmw:
            factor = 1.0 - 0.3 * (dist_km / rmw)
        else:
            factor = 0.7 * math.exp(-(dist_km - rmw) / (rmw * 2))
        return landfall_surge * factor

    def _inundation(self, surge_m: float, point: CoastalPoint) -> tuple:
        depth = max(0, surge_m - point.inland_elevation_m)
        if depth <= 0:
            return 0, 0
        slope    = 1/1000 if point.inland_elevation_m < 2 else 1/500 if point.inland_elevation_m < 5 else 1/200
        distance = depth / slope
        return depth, distance

    def _arrival_time(self, dist_km: float, hurricane: Hurricane) -> float:
        speed_kmh     = hurricane.forward_speed_mph * 1.609
        pre_hours     = hurricane.radius_max_wind_km / max(speed_kmh, 1)
        travel_hours  = dist_km / max(speed_kmh, 1)
        return max(0, (pre_hours - travel_hours) * 60)

    def _evac_zone(self, surge_m: float, inundation_m: float) -> str:
        if surge_m > 4.0 or inundation_m > 2.0:   return "Zone A — Mandatory evacuation"
        elif surge_m > 2.5 or inundation_m > 1.0: return "Zone B — Evacuation recommended"
        elif surge_m > 1.5:                        return "Zone C — Voluntary evacuation"
        return "Zone D — Monitor conditions"

    def _threat(self, surge_m: float, inundation_m: float) -> str:
        if surge_m > 4.0 or inundation_m > 2.0:   return "critical"
        elif surge_m > 2.0 or inundation_m > 1.0: return "high"
        elif surge_m > 1.0:                        return "medium"
        return "low"

    def calculate(self, hurricane: Hurricane, point: CoastalPoint) -> SLOSHResult:
        landfall_surge = self._surge_at_landfall(hurricane)
        surge          = self._surge_at_distance(landfall_surge, point.distance_from_landfall_km, hurricane)
        depth, dist    = self._inundation(surge, point)
        arrival        = self._arrival_time(point.distance_from_landfall_km, hurricane)
        people         = int(point.population * min(dist / 1000, 1.0)) if dist > 0 else 0
        threat         = self._threat(surge, depth)
        evac           = self._evac_zone(surge, depth)
        return SLOSHResult(
            point=point, hurricane=hurricane,
            surge_height_m=surge, inundation_depth_m=depth,
            inundation_distance_m=dist, arrival_time_min=arrival,
            threat_level=threat, people_at_risk=people,
            evacuation_zone=evac
        )

    def regional_assessment(self, hurricane: Hurricane,
                            points: List[CoastalPoint]) -> List[SLOSHResult]:
        return sorted([self.calculate(hurricane, p) for p in points],
                     key=lambda r: r.surge_height_m, reverse=True)

    def calculate_live(self, points: List[CoastalPoint]) -> List[SLOSHResult]:
        """
        Auto-fetch active NHC storms and calculate surge at coastal points.
        """
        print("[SLOSH] Fetching active hurricanes from NHC...")
        storms = get_active_hurricanes()

        if not storms:
            print("[SLOSH] No active tropical storms or hurricanes.")
            return []

        # Use strongest active storm
        strongest = max(storms, key=lambda s: s["wind_mph"])
        print(f"[SLOSH] Running on {strongest['name']} Cat{strongest['category']} "
              f"({strongest['wind_mph']}mph)")

        hurricane = Hurricane.from_live(strongest)

        # Calculate distance from storm center to each point
        for point in points:
            dist = self._haversine(
                hurricane.landfall_lat, hurricane.landfall_lon,
                point.lat, point.lon
            )
            point.distance_from_landfall_km = dist

        return self.regional_assessment(hurricane, points)

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        R = 6371.0
        d = lambda x: math.radians(x)
        a = (math.sin(d(lat2-lat1)/2)**2 +
             math.cos(d(lat1)) * math.cos(d(lat2)) *
             math.sin(d(lon2-lon1)/2)**2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def beacon_priority_zones(self, results: List[SLOSHResult]) -> dict:
        zones = {}
        color_map = {"critical": "red", "high": "orange",
                    "medium": "yellow", "low": "yellow"}
        for r in results:
            color = color_map[r.threat_level]
            if color not in zones:
                zones[color] = {
                    "priority":    {"red": 1, "orange": 2, "yellow": 3}[color],
                    "sites":       [],
                    "max_surge_m": 0,
                    "deploy":      "drone",
                    "label":       f"Storm surge — {r.threat_level}"
                }
            zones[color]["sites"].append(r.point.name)
            zones[color]["max_surge_m"] = max(zones[color]["max_surge_m"], r.surge_height_m)
        return zones


if __name__ == "__main__":
    model = SLOSHModel()
    print("🌀 NOAA SLOSH — Live NHC Storm Integration\n")

    # Gulf Coast sites for live assessment
    gulf_sites = [
        CoastalPoint("Galveston TX",        29.30, -94.80, 0, 8,  2,  50000),
        CoastalPoint("Houston Ship Channel", 29.75, -95.15, 0, 5,  8,  500000),
        CoastalPoint("New Orleans LA",       29.95, -90.07, 0, 5, -2,  500000),
        CoastalPoint("Mobile AL",            30.69, -88.04, 0, 6,  4,  200000),
        CoastalPoint("Tampa FL",             27.95, -82.46, 0, 7,  3,  400000),
        CoastalPoint("Miami FL",             25.77, -80.19, 0, 8,  2,  450000),
    ]

    print("=" * 55)
    print("LIVE MODE — Active NHC Storms")
    print("=" * 55)
    live_results = model.calculate_live(gulf_sites)
    if live_results:
        for r in live_results:
            print(f"\n📍 {r.point.name}")
            print(r.summary())
    else:
        print("No active tropical storms. Running Hurricane Harvey scenario.\n")
        harvey = Hurricane(
            "Harvey", HurricaneCategory.CAT4, 130, 938, 45, 10, 330, 28.0, -97.0
        )
        harvey_points = [
            CoastalPoint("Rockport TX",     28.02, -97.05,  5, 10, 3, 10000),
            CoastalPoint("Port Aransas TX", 27.83, -97.07, 25, 15, 2,  4000),
            CoastalPoint("Corpus Christi",  27.80, -97.40, 45, 20, 5, 320000),
            CoastalPoint("Galveston TX",    29.30, -94.80,150,  8, 2,  50000),
        ]
        for r in model.regional_assessment(harvey, harvey_points):
            print(f"\n📍 {r.point.name}")
            print(r.summary())