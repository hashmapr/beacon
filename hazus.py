import math
import requests
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from shakemap import ShakeMap, ShakeMapResult, EarthquakeEvent, get_largest_nearby_quake


@dataclass
class BuildingType:
    code: str
    name: str
    slight_threshold: float
    moderate_threshold: float
    extensive_threshold: float
    complete_threshold: float
    casualty_rate_complete: float


BUILDING_TYPES = {
    "W1":  BuildingType("W1",  "Wood Single Family",      0.10, 0.25, 0.50, 0.80, 0.05),
    "W2":  BuildingType("W2",  "Wood Commercial",         0.12, 0.30, 0.60, 1.00, 0.04),
    "S1L": BuildingType("S1L", "Steel Moment Frame Low",  0.15, 0.35, 0.70, 1.20, 0.03),
    "S1M": BuildingType("S1M", "Steel Moment Frame Mid",  0.12, 0.28, 0.55, 0.95, 0.04),
    "S1H": BuildingType("S1H", "Steel Moment Frame High", 0.10, 0.25, 0.50, 0.85, 0.05),
    "C1L": BuildingType("C1L", "Concrete Frame Low",      0.12, 0.28, 0.55, 0.90, 0.06),
    "C1M": BuildingType("C1M", "Concrete Frame Mid",      0.10, 0.22, 0.45, 0.75, 0.07),
    "C1H": BuildingType("C1H", "Concrete Frame High",     0.08, 0.18, 0.38, 0.65, 0.08),
    "C2L": BuildingType("C2L", "Concrete Shear Wall Low", 0.15, 0.35, 0.70, 1.10, 0.05),
    "URM": BuildingType("URM", "Unreinforced Masonry",    0.06, 0.14, 0.28, 0.50, 0.15),
    "MH":  BuildingType("MH",  "Mobile Home",             0.08, 0.18, 0.35, 0.60, 0.08),
}


@dataclass
class DamageState:
    building_type: str
    pga: float
    prob_slight: float
    prob_moderate: float
    prob_extensive: float
    prob_complete: float
    expected_damage_state: str
    structural_loss_ratio: float


@dataclass
class CasualtyEstimate:
    indoor_casualties: int
    indoor_fatalities: int
    outdoor_casualties: int
    total_affected: int
    severity_1: int
    severity_2: int
    severity_3: int
    severity_4: int


@dataclass
class HAZUSResult:
    event: EarthquakeEvent
    site_lat: float
    site_lon: float
    pga: float
    mmi: float
    damage_states: Dict[str, DamageState]
    casualties: CasualtyEstimate
    fire_ignition_probability: float
    utility_damage: Dict[str, float]
    threat_level: str
    beacon_priority: int
    live_data: bool
    quake_place: str

    def summary(self):
        lines = [
            f"Source:        {'LIVE USGS' if self.live_data else 'Manual input'}",
            f"Event:         {self.quake_place}",
            f"PGA: {self.pga:.4f}g  MMI: {self.mmi:.1f}",
            f"Threat: {self.threat_level.upper()}",
            f"",
            f"STRUCTURAL DAMAGE:"
        ]
        for code, state in self.damage_states.items():
            lines.append(
                f"  {code:5s} ({BUILDING_TYPES[code].name[:20]:20s}): "
                f"{state.expected_damage_state:10s} "
                f"[complete: {state.prob_complete*100:.0f}%]"
            )
        lines.extend([
            f"",
            f"CASUALTY ESTIMATES:",
            f"  Minor injuries:      {self.casualties.severity_1}",
            f"  Hospitalized:        {self.casualties.severity_2}",
            f"  Life threatening:    {self.casualties.severity_3}",
            f"  Fatalities:          {self.casualties.severity_4}",
            f"  Total affected:      {self.casualties.total_affected}",
            f"",
            f"SECONDARY HAZARDS:",
            f"  Fire ignition prob:  {self.fire_ignition_probability*100:.0f}%",
            f"  Power system:        {self.utility_damage['power']*100:.0f}% damaged",
            f"  Water system:        {self.utility_damage['water']*100:.0f}% damaged",
            f"  Road network:        {self.utility_damage['roads']*100:.0f}% damaged",
        ])
        return "\n".join(lines)


class HAZUSModel:
    """
    FEMA HAZUS Earthquake Loss Estimation.
    Pulls live USGS earthquake data automatically.
    """

    def __init__(self):
        self.shakemap = ShakeMap()

    def _fragility_curve(self, pga: float, threshold: float, beta: float = 0.6) -> float:
        if pga <= 0 or threshold <= 0:
            return 0.0
        z = math.log(pga / threshold) / beta
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))

    def _damage_state(self, building: BuildingType, pga: float) -> DamageState:
        p_slight    = self._fragility_curve(pga, building.slight_threshold)
        p_moderate  = self._fragility_curve(pga, building.moderate_threshold)
        p_extensive = self._fragility_curve(pga, building.extensive_threshold)
        p_complete  = self._fragility_curve(pga, building.complete_threshold)

        if p_complete > 0.50:
            expected, loss = "COMPLETE", 0.85
        elif p_extensive > 0.50:
            expected, loss = "EXTENSIVE", 0.45
        elif p_moderate > 0.50:
            expected, loss = "MODERATE", 0.15
        elif p_slight > 0.50:
            expected, loss = "SLIGHT", 0.03
        else:
            expected, loss = "NONE", 0.0

        return DamageState(
            building_type=building.code, pga=pga,
            prob_slight=p_slight, prob_moderate=p_moderate,
            prob_extensive=p_extensive, prob_complete=p_complete,
            expected_damage_state=expected, structural_loss_ratio=loss
        )

    def _estimate_casualties(self, damage_states: Dict[str, DamageState], population: int = 10000) -> CasualtyEstimate:
        rates = {
            "COMPLETE":  {"s1": 0.05,   "s2": 0.01,   "s3": 0.001,   "s4": 0.0001},
            "EXTENSIVE": {"s1": 0.01,   "s2": 0.001,  "s3": 0.0001,  "s4": 0.00001},
            "MODERATE":  {"s1": 0.005,  "s2": 0.0001, "s3": 0.00001, "s4": 0.0},
            "SLIGHT":    {"s1": 0.0005, "s2": 0.0,    "s3": 0.0,     "s4": 0.0},
            "NONE":      {"s1": 0.0,    "s2": 0.0,    "s3": 0.0,     "s4": 0.0},
        }
        s1 = s2 = s3 = s4 = 0
        for code, state in damage_states.items():
            r = rates.get(state.expected_damage_state, rates["NONE"])
            pop = population / len(damage_states)
            s1 += int(pop * r["s1"])
            s2 += int(pop * r["s2"])
            s3 += int(pop * r["s3"])
            s4 += int(pop * r["s4"])
        return CasualtyEstimate(
            indoor_casualties=s1+s2+s3, indoor_fatalities=s4,
            outdoor_casualties=int(s1*0.1), total_affected=s1+s2+s3+s4,
            severity_1=s1, severity_2=s2, severity_3=s3, severity_4=s4
        )

    def _fire_ignition_probability(self, pga: float) -> float:
        if pga < 0.10:   return 0.01
        elif pga < 0.20: return 0.05
        elif pga < 0.40: return 0.15
        elif pga < 0.60: return 0.35
        else:            return 0.60

    def _utility_damage(self, pga: float) -> Dict[str, float]:
        return {
            "power":   min(pga * 2.5, 1.0),
            "water":   min(pga * 3.0, 1.0),
            "gas":     min(pga * 2.0, 1.0),
            "roads":   min(pga * 1.5, 1.0),
            "bridges": min(pga * 3.5, 1.0),
        }

    def _threat_from_damage(self, damage_states: Dict[str, DamageState]) -> tuple:
        complete  = sum(1 for s in damage_states.values() if s.expected_damage_state == "COMPLETE")
        extensive = sum(1 for s in damage_states.values() if s.expected_damage_state == "EXTENSIVE")
        if complete >= 3:   return "critical", 1
        elif complete >= 1 or extensive >= 3: return "high", 2
        elif extensive >= 1: return "medium", 3
        return "low", 4

    def calculate(self, event: EarthquakeEvent, site_lat: float, site_lon: float,
                  vs30: float = 360.0, population: int = 10000,
                  live_data: bool = False, quake_place: str = "Manual input") -> HAZUSResult:
        shake = self.shakemap.calculate(event, site_lat, site_lon, vs30)
        pga = shake.pga
        damage_states = {code: self._damage_state(building, pga)
                        for code, building in BUILDING_TYPES.items()}
        casualties  = self._estimate_casualties(damage_states, population)
        fire_prob   = self._fire_ignition_probability(pga)
        utility     = self._utility_damage(pga)
        threat, pri = self._threat_from_damage(damage_states)
        return HAZUSResult(
            event=event, site_lat=site_lat, site_lon=site_lon,
            pga=pga, mmi=shake.mmi, damage_states=damage_states,
            casualties=casualties, fire_ignition_probability=fire_prob,
            utility_damage=utility, threat_level=threat,
            beacon_priority=pri, live_data=live_data, quake_place=quake_place
        )

    def calculate_live(self, site_lat: float, site_lon: float,
                       radius_km: float = 500, vs30: float = 360.0,
                       population: int = 10000) -> Optional[HAZUSResult]:
        """Auto-fetch largest nearby earthquake and run HAZUS."""
        print(f"[HAZUS] Fetching live earthquake data near ({site_lat}, {site_lon})...")
        quake = get_largest_nearby_quake(site_lat, site_lon, radius_km)
        if not quake:
            print("[HAZUS] No significant earthquakes found nearby.")
            return None
        print(f"[HAZUS] Running on M{quake['magnitude']} — {quake['place']}")
        event = EarthquakeEvent.from_live(quake)
        return self.calculate(event, site_lat, site_lon, vs30, population,
                              live_data=True, quake_place=quake["place"])

    def beacon_priority_zones(self, event: EarthquakeEvent,
                              center_lat: float, center_lon: float) -> dict:
        zones = {}
        for i, (radius, color) in enumerate([(5, "red"), (20, "orange"), (50, "yellow")]):
            site_lat = center_lat + radius / 111.0
            result = self.calculate(event, site_lat, center_lon)
            zones[color] = {
                "priority": i + 1, "radius_km": radius,
                "pga": result.pga, "mmi": result.mmi,
                "threat": result.threat_level,
                "casualties": result.casualties.total_affected,
                "fire_risk": result.fire_ignition_probability,
                "deploy": "drone" if i == 0 else "rover",
                "label": f"MMI {result.mmi:.1f} — {result.threat_level}"
            }
        return zones


if __name__ == "__main__":
    model = HAZUSModel()
    print("🏚️  FEMA HAZUS — Live USGS Earthquake Integration\n")

    # Live mode
    locations = [
        ("Los Angeles CA",  34.05, -118.25, 360, 500000),
        ("Anchorage AK",    61.22, -149.90, 360, 300000),
        ("Salt Lake City UT", 40.76, -111.89, 360, 200000),
    ]

    for name, lat, lon, vs30, pop in locations:
        print(f"\n{'='*55}")
        print(f"LOCATION: {name}")
        print(f"{'='*55}")
        result = model.calculate_live(lat, lon, radius_km=800, vs30=vs30, population=pop)
        if result:
            print(result.summary())
        else:
            print("No significant seismic activity detected.")

    # Manual
    print(f"\n{'='*55}")
    print("MANUAL: 2023 Morocco M6.8")
    print(f"{'='*55}")
    event = EarthquakeEvent(6.8, 18.5, 31.12, -8.38, "strike_slip")
    result = model.calculate(event, 31.20, -8.30, 180, 5000)
    print(result.summary())