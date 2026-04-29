import math
import requests
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum
from datetime import datetime


# ── LIVE TERRAIN & WEATHER ───────────────────────────────────────

def get_terrain_type(lat: float, lon: float) -> str:
    """
    Estimate terrain type from USGS National Land Cover Database.
    Falls back to heuristic based on coordinates.
    """
    try:
        # USGS National Map elevation service to get context
        url = "https://epqs.nationalmap.gov/v1/json"
        params = {"x": lon, "y": lat, "wkid": 4326, "includeDate": False}
        r = requests.get(url, params=params, timeout=8)
        elev = float(r.json()["value"])

        if elev > 2000:   return "mountain"
        elif elev > 500:  return "forest"
        elif elev < 10:   return "urban_fringe"
        else:             return "forest"
    except:
        # Heuristic fallback
        if abs(lat) > 50:   return "mountain"
        elif abs(lon) < 100: return "forest"
        else:               return "forest"


def get_live_weather_for_sar(lat: float, lon: float) -> dict:
    """Pull current weather conditions for SAR planning."""
    headers = {"User-Agent": "Beacon-Disaster-Response/1.0"}
    try:
        r = requests.get(f"https://api.weather.gov/points/{lat},{lon}",
                        headers=headers, timeout=10)
        r.raise_for_status()
        stations_url = r.json()["properties"]["observationStations"]
        r2 = requests.get(stations_url, headers=headers, timeout=10)
        station_id = r2.json()["features"][0]["properties"]["stationIdentifier"]
        r3 = requests.get(
            f"https://api.weather.gov/stations/{station_id}/observations/latest",
            headers=headers, timeout=10
        )
        obs      = r3.json()["properties"]
        temp_c   = obs.get("temperature",      {}).get("value") or 15
        humidity = obs.get("relativeHumidity", {}).get("value") or 60
        wind_ms  = obs.get("windSpeed",        {}).get("value") or 2
        vis_m    = obs.get("visibility",       {}).get("value") or 10000

        return {
            "temperature_c": temp_c,
            "humidity_pct":  humidity,
            "wind_speed_ms": wind_ms,
            "visibility_m":  vis_m,
            "station":       station_id,
            "survival_window_modifier": _survival_modifier(temp_c, humidity, wind_ms)
        }
    except Exception as e:
        print(f"[NOAA] SAR weather fetch error: {e}")
        return {"survival_window_modifier": 1.0}


def _survival_modifier(temp_c: float, humidity: float, wind_ms: float) -> float:
    """
    Modify survival probability based on environmental conditions.
    Cold + wet + windy = faster survival window closure.
    """
    modifier = 1.0
    if temp_c < 5:    modifier *= 0.7   # hypothermia risk
    elif temp_c > 38: modifier *= 0.6   # heat exhaustion
    if humidity > 90: modifier *= 0.85  # wet increases heat loss
    if wind_ms > 10:  modifier *= 0.80  # wind chill
    return modifier


# ── MATTSON MODEL ────────────────────────────────────────────────

class SubjectCategory(Enum):
    HIKER          = "hiker"
    CHILD_1_3      = "child_1_3"
    CHILD_4_6      = "child_4_6"
    CHILD_7_9      = "child_7_9"
    CHILD_10_12    = "child_10_12"
    CHILD_13_15    = "child_13_15"
    DEMENTIA       = "dementia"
    DESPONDENT     = "despondent"
    HUNTER         = "hunter"
    CLIMBER        = "climber"
    SKIER          = "skier"
    MOUNTAIN_BIKER = "mountain_biker"
    TRAIL_RUNNER   = "trail_runner"
    HORSEBACK      = "horseback"


@dataclass
class SubjectProfile:
    category: SubjectCategory
    travel_speed_mph: float
    max_distance_km: float
    trail_tendency: float
    downhill_tendency: float
    water_tendency: float
    shelter_tendency: float
    description: str


SUBJECT_PROFILES = {
    SubjectCategory.HIKER:          SubjectProfile(SubjectCategory.HIKER,          1.5, 8.0,  0.79, 0.65, 0.45, 0.30, "Hikers stay on trails, move downhill toward water"),
    SubjectCategory.CHILD_1_3:      SubjectProfile(SubjectCategory.CHILD_1_3,      0.5, 0.5,  0.10, 0.50, 0.70, 0.80, "Very young children move randomly, seek hiding spots"),
    SubjectCategory.CHILD_4_6:      SubjectProfile(SubjectCategory.CHILD_4_6,      0.8, 1.2,  0.15, 0.55, 0.65, 0.75, "Young children attracted to water, hide in small spaces"),
    SubjectCategory.CHILD_7_9:      SubjectProfile(SubjectCategory.CHILD_7_9,      1.0, 2.5,  0.25, 0.60, 0.60, 0.60, "Children begin following trails, attracted to water"),
    SubjectCategory.CHILD_10_12:    SubjectProfile(SubjectCategory.CHILD_10_12,    1.2, 4.0,  0.40, 0.62, 0.55, 0.50, "Pre-teen hikers, moderate trail following"),
    SubjectCategory.DEMENTIA:       SubjectProfile(SubjectCategory.DEMENTIA,       0.8, 3.5,  0.20, 0.45, 0.40, 0.25, "Wander randomly, avoid trails, may hide"),
    SubjectCategory.DESPONDENT:     SubjectProfile(SubjectCategory.DESPONDENT,     1.2, 5.5,  0.35, 0.50, 0.55, 0.20, "Move away from people, avoid trails, seek isolation"),
    SubjectCategory.HUNTER:         SubjectProfile(SubjectCategory.HUNTER,         1.5, 6.5,  0.50, 0.60, 0.65, 0.55, "Leave trails, move toward game habitat and water"),
    SubjectCategory.CLIMBER:        SubjectProfile(SubjectCategory.CLIMBER,        1.0, 5.0,  0.45, 0.35, 0.30, 0.65, "May go uphill, seek cliff faces and technical terrain"),
    SubjectCategory.SKIER:          SubjectProfile(SubjectCategory.SKIER,          2.0, 7.0,  0.60, 0.80, 0.40, 0.50, "Follow fall lines downhill, seek open terrain"),
    SubjectCategory.TRAIL_RUNNER:   SubjectProfile(SubjectCategory.TRAIL_RUNNER,   4.0, 15.0, 0.85, 0.55, 0.40, 0.20, "Stay on trails, cover large distances quickly"),
    SubjectCategory.MOUNTAIN_BIKER: SubjectProfile(SubjectCategory.MOUNTAIN_BIKER, 5.0, 20.0, 0.90, 0.60, 0.35, 0.20, "Stay on trails, cover very large distances"),
    SubjectCategory.HORSEBACK:      SubjectProfile(SubjectCategory.HORSEBACK,      3.0, 12.0, 0.75, 0.55, 0.50, 0.40, "Follow trails and open terrain"),
}


@dataclass
class SearchArea:
    zone_name: str
    min_distance_km: float
    max_distance_km: float
    probability: float
    priority: int
    bearing_range: Tuple[float, float]


@dataclass
class MattsonResult:
    subject_category: str
    lkp_lat: float
    lkp_lon: float
    hours_missing: float
    search_areas: List[SearchArea]
    total_probability: float
    recommended_deployment: str
    terrain_type: str
    weather_conditions: dict
    survival_probability: float

    def summary(self):
        lines = [
            f"Subject:           {self.subject_category}",
            f"LKP:               ({self.lkp_lat}, {self.lkp_lon})",
            f"Hours Missing:     {self.hours_missing}h",
            f"Terrain:           {self.terrain_type}",
            f"Survival Prob:     {self.survival_probability*100:.0f}%",
            f"Total Coverage:    {self.total_probability*100:.0f}%",
            f"",
            f"SEARCH ZONES (priority order):"
        ]
        for zone in sorted(self.search_areas, key=lambda z: z.priority):
            lines.append(
                f"  Zone {zone.priority} [{zone.zone_name}]: "
                f"{zone.min_distance_km:.1f}-{zone.max_distance_km:.1f}km from LKP — "
                f"{zone.probability*100:.0f}% probability"
            )
        lines.append(f"\nDeploy: {self.recommended_deployment}")
        return "\n".join(lines)


class MattsonModel:
    """
    Mattson Lost Person Probability Model.
    Automatically pulls live terrain type and weather conditions.

    References:
    - Mattson 1980. Probability Modeling for Search and Rescue.
    - Koester 2008. Lost Person Behavior. dbS Productions.
    - ISRID International Search and Rescue Incident Database.
    """

    def _distance_probability(self, distance_km: float, profile: SubjectProfile, hours: float) -> float:
        max_travel = min(profile.travel_speed_mph * hours * 1.609, profile.max_distance_km)
        max_travel = max(max_travel, 0.1)
        decay_lambda = 2.0 / max_travel
        return decay_lambda * math.exp(-decay_lambda * distance_km)

    def _terrain_modifier(self, profile: SubjectProfile, terrain_type: str) -> dict:
        modifiers = {
            "forest":      {"trail": profile.trail_tendency,       "water": profile.water_tendency},
            "mountain":    {"trail": profile.trail_tendency * 0.8, "water": profile.water_tendency * 0.7},
            "desert":      {"trail": profile.trail_tendency * 0.6, "water": profile.water_tendency * 1.5},
            "urban_fringe":{"trail": profile.trail_tendency * 1.2, "water": profile.water_tendency * 0.8},
        }
        return modifiers.get(terrain_type, modifiers["forest"])

    def _survival_probability(self, hours: float, weather_modifier: float,
                               profile: SubjectProfile) -> float:
        """
        Estimate survival probability based on time, weather, and subject type.
        Based on ISRID statistical survival data.
        """
        # Base decay: ~50% survive 72h in moderate conditions
        base_decay = math.exp(-hours / 72.0)

        # Subject vulnerability
        vulnerability = {
            SubjectCategory.CHILD_1_3:   0.7,
            SubjectCategory.CHILD_4_6:   0.75,
            SubjectCategory.DEMENTIA:    0.65,
            SubjectCategory.DESPONDENT:  0.60,
            SubjectCategory.HIKER:       0.95,
            SubjectCategory.HUNTER:      0.92,
            SubjectCategory.CLIMBER:     0.85,
        }.get(profile.category, 0.90)

        return min(1.0, base_decay * vulnerability * weather_modifier)

    def calculate(self, lkp_lat: float, lkp_lon: float,
                  subject_category: SubjectCategory, hours_missing: float,
                  terrain_type: str = None, use_live_data: bool = True) -> MattsonResult:
        """
        Calculate survivor probability distribution.
        Automatically pulls live terrain and weather when use_live_data=True.
        """
        profile = SUBJECT_PROFILES[subject_category]
        weather = {}
        survival_modifier = 1.0

        if use_live_data:
            print(f"[MATTSON] Fetching live conditions for ({lkp_lat}, {lkp_lon})...")
            if not terrain_type:
                terrain_type = get_terrain_type(lkp_lat, lkp_lon)
                print(f"[MATTSON] Terrain type: {terrain_type}")
            weather = get_live_weather_for_sar(lkp_lat, lkp_lon)
            survival_modifier = weather.get("survival_window_modifier", 1.0)
            if survival_modifier < 1.0:
                print(f"[MATTSON] Survival modifier: {survival_modifier:.2f} (adverse conditions)")

        terrain_type = terrain_type or "forest"
        terrain = self._terrain_modifier(profile, terrain_type)

        max_travel = min(profile.travel_speed_mph * hours_missing * 1.609,
                        profile.max_distance_km)

        # Build search zones
        zones = []

        d1_max = max(max_travel * 0.25, 0.3)
        p1 = self._distance_probability(d1_max / 2, profile, hours_missing)
        p1 *= (1.0 + profile.trail_tendency * 0.5)
        zones.append(SearchArea("IMMEDIATE", 0.0, d1_max,
                                min(p1 * d1_max, 0.55), 1, (0, 360)))

        d2_min = d1_max
        d2_max = max(max_travel * 0.60, 0.8)
        p2 = self._distance_probability((d2_min + d2_max) / 2, profile, hours_missing)
        p2 *= terrain["trail"] + terrain["water"] * 0.5
        zones.append(SearchArea("HIGH PROBABILITY", d2_min, d2_max,
                                min(p2 * (d2_max - d2_min), 0.35), 2, (0, 360)))

        d3_min = d2_max
        d3_max = max_travel
        p3 = self._distance_probability(d3_max * 0.8, profile, hours_missing)
        zones.append(SearchArea("EXTENDED", d3_min, max(d3_max, d3_min + 0.5),
                                min(p3 * (d3_max - d3_min + 0.1), 0.15), 3, (0, 360)))

        zones.append(SearchArea("CONTAINMENT", d3_max, d3_max * 1.5,
                                0.05, 4, (0, 360)))

        total_prob = min(sum(z.probability for z in zones), 1.0)
        survival   = self._survival_probability(hours_missing, survival_modifier, profile)

        # Deployment recommendation
        if subject_category in [SubjectCategory.CHILD_1_3, SubjectCategory.CHILD_4_6]:
            deploy = "Thermal drone sweep immediate area — children hide, look for heat signature"
        elif subject_category == SubjectCategory.DEMENTIA:
            deploy = "Ground rover + thermal drone — scan off-trail systematically"
        elif subject_category in [SubjectCategory.TRAIL_RUNNER, SubjectCategory.MOUNTAIN_BIKER]:
            deploy = "Extended aerial sweep along trail network — high mobility subject"
        elif subject_category == SubjectCategory.DESPONDENT:
            deploy = "Thermal drone — isolated areas, water bodies, dense vegetation"
        else:
            deploy = "Thermal drone immediate zone first, rover on trails, extended sweep if not found"

        return MattsonResult(
            subject_category=subject_category.value,
            lkp_lat=lkp_lat, lkp_lon=lkp_lon,
            hours_missing=hours_missing,
            search_areas=zones,
            total_probability=total_prob,
            recommended_deployment=deploy,
            terrain_type=terrain_type,
            weather_conditions=weather,
            survival_probability=survival
        )

    def beacon_priority_zones(self, result: MattsonResult) -> dict:
        zones = {}
        color_map = {1: "red", 2: "orange", 3: "yellow", 4: "white"}
        for area in result.search_areas:
            color = color_map.get(area.priority, "white")
            if color == "white":
                continue
            zones[color] = {
                "priority":    area.priority,
                "label":       f"SAR {area.zone_name}",
                "min_km":      area.min_distance_km,
                "max_km":      area.max_distance_km,
                "probability": area.probability,
                "center":      {"lat": result.lkp_lat, "lon": result.lkp_lon},
                "deploy":      "drone" if area.priority <= 2 else "rover",
                "survival_pct": result.survival_probability * 100
            }
        return zones


if __name__ == "__main__":
    model = MattsonModel()
    print("🔍 MATTSON SAR MODEL — Live Terrain & Weather Integration\n")

    scenarios = [
        ("Lost Hiker — Yosemite",         37.74, -119.59, SubjectCategory.HIKER,     6),
        ("Missing Child — Allen TX Park",  33.10,  -96.67, SubjectCategory.CHILD_4_6, 2),
        ("Dementia Patient — Dallas",      32.90,  -96.75, SubjectCategory.DEMENTIA,  4),
        ("Trail Runner — CO Wilderness",   38.05, -106.45, SubjectCategory.TRAIL_RUNNER, 3),
    ]

    for name, lat, lon, cat, hours in scenarios:
        print(f"\n{'='*55}")
        print(f"SCENARIO: {name}")
        print(f"{'='*55}")
        result = model.calculate(lat, lon, cat, hours, use_live_data=True)
        print(result.summary())