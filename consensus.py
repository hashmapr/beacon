import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

from rothermel import RothermelModel, FireEnvironment, FireBehavior
from mattson import MattsonModel, SubjectCategory, MattsonResult
from noaa_feed import NOAAFeed, WeatherConditions
from fairsite_wrapper import predict_fire_spread
from shakemap import ShakeMap, EarthquakeEvent, ShakeMapResult
from hazus import HAZUSModel, HAZUSResult
from trigrs import TRIGRSModel, RainfallInput, SLOPE_PROFILES
from most import MOSTModel, TsunamiSource, CoastalSite
from aloha import ALOHAModel, ReleaseScenario, AtmosphericConditions, ReleaseType

@dataclass
class ConsensusZone:
    lat: float
    lon: float
    radius_km: float
    color: str
    priority: int
    models_agreeing: List[str]
    threat_level: str
    probability: float
    deploy: str
    label: str

@dataclass
class ConsensusMap:
    location_lat: float
    location_lon: float
    zones: List[ConsensusZone]
    weather: Optional[WeatherConditions]
    active_models: List[str]
    timestamp: str
    scenario: str

    def summary(self):
        lines = [
            f"\n{'='*60}",
            f"BEACON CONSENSUS PRIORITY MAP",
            f"{'='*60}",
            f"Scenario:  {self.scenario.upper()}",
            f"Location:  ({self.location_lat}, {self.location_lon})",
            f"Models:    {', '.join(self.active_models)}",
            f"Time:      {self.timestamp}",
            f"",
            f"PRIORITY ZONES:",
        ]
        for zone in sorted(self.zones, key=lambda z: z.priority):
            lines.append(f"\n  [{zone.color.upper()}] Zone {zone.priority} — {zone.label}")
            lines.append(f"  Models:  {', '.join(zone.models_agreeing)}")
            lines.append(f"  Radius:  {zone.radius_km:.1f}km")
            lines.append(f"  Threat:  {zone.threat_level.upper()}")
            lines.append(f"  Deploy:  {zone.deploy.upper()}")
        return "\n".join(lines)


class BeaconConsensus:
    """
    Beacon Multi-Model Consensus System.
    Combines all predictive models into one unified priority map.
    Supports: wildfire, earthquake, tsunami, landslide, chemical, SAR, all
    """

    def __init__(self):
        self.rothermel = RothermelModel()
        self.mattson = MattsonModel()
        self.noaa = NOAAFeed()
        self.shakemap = ShakeMap()
        self.hazus = HAZUSModel()
        self.trigrs = TRIGRSModel()
        self.most = MOSTModel()
        self.aloha = ALOHAModel()

    def _get_weather(self, lat, lon):
        """Fetch live NOAA weather with fallback."""
        try:
            data = self.noaa.get_fire_weather(lat, lon)
            print(f"[CONSENSUS] Weather: {data['wind_speed']:.1f}mph, "
                  f"{data['conditions'].humidity:.0f}% humidity")
            return data
        except Exception as e:
            print(f"[CONSENSUS] NOAA unavailable: {e} — using defaults")
            return {
                "wind_speed": 10.0, "wind_direction": 270.0,
                "moisture_1hr": 0.10, "moisture_10hr": 0.15,
                "moisture_100hr": 0.20, "moisture_live": 0.80,
                "conditions": None
            }

    def run_wildfire(self, lat, lon, weather_data, fuel_model=4, slope=10) -> dict:
        """Run wildfire models: Rothermel + FARSITE."""
        results = {}

        # Rothermel
        try:
            env = FireEnvironment(
                fuel_model=fuel_model,
                wind_speed=weather_data["wind_speed"],
                wind_direction=weather_data["wind_direction"],
                slope=slope, aspect=180,
                moisture_1hr=weather_data["moisture_1hr"],
                moisture_10hr=weather_data["moisture_10hr"],
                moisture_100hr=weather_data["moisture_100hr"],
                moisture_live=weather_data["moisture_live"]
            )
            behavior = self.rothermel.calculate(env)
            threat = self.rothermel.threat_level(behavior)
            results["rothermel"] = {"threat": threat, "behavior": behavior}
            print(f"[CONSENSUS] Rothermel: {behavior.spread_rate_mph:.2f}mph, threat={threat}")
        except Exception as e:
            print(f"[CONSENSUS] Rothermel error: {e}")

        # FARSITE
        try:
            farsite_zones = predict_fire_spread(
                ignition_lat=lat, ignition_lon=lon,
                wind_speed=weather_data["wind_speed"],
                wind_direction=weather_data["wind_direction"],
                fuel_moisture=weather_data["moisture_1hr"] * 100,
                duration_hours=6
            )
            results["farsite"] = farsite_zones
            print(f"[CONSENSUS] FARSITE: {len(farsite_zones)} zones generated")
        except Exception as e:
            print(f"[CONSENSUS] FARSITE error: {e}")

        return results

    def run_earthquake(self, lat, lon, event: EarthquakeEvent) -> dict:
        """Run earthquake models: ShakeMap + HAZUS."""
        results = {}

        try:
            shake = self.shakemap.calculate(event, lat, lon)
            results["shakemap"] = shake
            print(f"[CONSENSUS] ShakeMap: PGA={shake.pga:.4f}g, MMI={shake.mmi:.1f}")
        except Exception as e:
            print(f"[CONSENSUS] ShakeMap error: {e}")

        try:
            hazus = self.hazus.calculate(event, lat, lon)
            results["hazus"] = hazus
            print(f"[CONSENSUS] HAZUS: threat={hazus.threat_level}, "
                  f"casualties={hazus.casualties.total_affected}")
        except Exception as e:
            print(f"[CONSENSUS] HAZUS error: {e}")

        return results

    def run_tsunami(self, lat, lon, source: TsunamiSource, sites: list) -> dict:
        """Run tsunami model: MOST."""
        results = {}
        try:
            impacts = self.most.regional_assessment(source, sites)
            results["most"] = impacts
            critical = sum(1 for i in impacts if i.threat_level == "critical")
            print(f"[CONSENSUS] MOST: {critical} critical coastal sites")
        except Exception as e:
            print(f"[CONSENSUS] MOST error: {e}")
        return results

    def run_landslide(self, rainfall: RainfallInput, hours: float) -> dict:
        """Run landslide model: TRIGRS."""
        results = {}
        try:
            trigrs_results = self.trigrs.regional_assessment(rainfall, hours)
            critical = sum(1 for r in trigrs_results if r.threat_level == "critical")
            results["trigrs"] = trigrs_results
            print(f"[CONSENSUS] TRIGRS: {critical} slopes at critical failure risk")
        except Exception as e:
            print(f"[CONSENSUS] TRIGRS error: {e}")
        return results

    def run_chemical(self, scenario: ReleaseScenario, atm: AtmosphericConditions) -> dict:
        """Run chemical model: ALOHA."""
        results = {}
        try:
            aloha_result = self.aloha.calculate(scenario, atm)
            results["aloha"] = aloha_result
            print(f"[CONSENSUS] ALOHA: max hazard {aloha_result.max_downwind_distance_m:.0f}m")
        except Exception as e:
            print(f"[CONSENSUS] ALOHA error: {e}")
        return results

    def run_sar(self, lat, lon, category: SubjectCategory, hours: float, terrain: str) -> dict:
        """Run SAR model: Mattson."""
        results = {}
        try:
            sar = self.mattson.calculate(lat, lon, category, hours, terrain)
            results["mattson"] = sar
            print(f"[CONSENSUS] Mattson: zone 1 probability "
                  f"{sar.search_areas[0].probability*100:.0f}%")
        except Exception as e:
            print(f"[CONSENSUS] Mattson error: {e}")
        return results

    def build_zones(self, model_outputs: dict, lat: float, lon: float) -> List[ConsensusZone]:
        """Build consensus priority zones from all model outputs."""
        zones = []
        red_models, orange_models, yellow_models = [], [], []

        # Wildfire
        if "rothermel" in model_outputs:
            threat = model_outputs["rothermel"]["threat"]
            if threat == "critical":
                red_models.append("Rothermel")
            elif threat in ["high", "medium"]:
                orange_models.append("Rothermel")
            else:
                yellow_models.append("Rothermel")

        if "farsite" in model_outputs:
            red_models.append("FARSITE")

        # Earthquake
        if "hazus" in model_outputs:
            h = model_outputs["hazus"]
            if h.threat_level == "critical":
                red_models.append("HAZUS")
            elif h.threat_level == "high":
                orange_models.append("HAZUS")
            else:
                yellow_models.append("HAZUS")

        if "shakemap" in model_outputs:
            s = model_outputs["shakemap"]
            if s.threat_level in ["critical", "high"]:
                orange_models.append("ShakeMap")
            else:
                yellow_models.append("ShakeMap")

        # Tsunami
        if "most" in model_outputs:
            critical_sites = sum(
                1 for i in model_outputs["most"] if i.threat_level == "critical"
            )
            if critical_sites > 0:
                red_models.append("MOST")
            else:
                orange_models.append("MOST")

        # Landslide
        if "trigrs" in model_outputs:
            critical_slopes = sum(
                1 for r in model_outputs["trigrs"] if r.threat_level == "critical"
            )
            if critical_slopes >= 2:
                red_models.append("TRIGRS")
            elif critical_slopes == 1:
                orange_models.append("TRIGRS")
            else:
                yellow_models.append("TRIGRS")

        # Chemical
        if "aloha" in model_outputs:
            a = model_outputs["aloha"]
            critical_zones = [z for z in a.threat_zones if z.threat_level == "critical"]
            if critical_zones:
                red_models.append("ALOHA")
            else:
                orange_models.append("ALOHA")

        # SAR
        if "mattson" in model_outputs:
            m = model_outputs["mattson"]
            if m.search_areas[0].probability > 0.45:
                red_models.append("Mattson")
            else:
                orange_models.append("Mattson")

        # Build zones
        if red_models:
            zones.append(ConsensusZone(
                lat=lat, lon=lon, radius_km=5.0, color="red", priority=1,
                models_agreeing=red_models, threat_level="critical",
                probability=0.90, deploy="drone",
                label=f"CRITICAL — {len(red_models)} model(s) agree"
            ))

        if orange_models:
            zones.append(ConsensusZone(
                lat=lat, lon=lon, radius_km=15.0, color="orange", priority=2,
                models_agreeing=orange_models, threat_level="high",
                probability=0.65, deploy="rover",
                label=f"HIGH — {len(orange_models)} model(s) flagged"
            ))

        all_models = list(set(red_models + orange_models + yellow_models))
        zones.append(ConsensusZone(
            lat=lat, lon=lon, radius_km=40.0, color="yellow", priority=3,
            models_agreeing=all_models, threat_level="medium",
            probability=0.35, deploy="drone",
            label="MODERATE — monitoring active"
        ))

        return zones

    def run(
        self,
        lat: float,
        lon: float,
        scenario: str = "wildfire",
        # Wildfire params
        fuel_model: int = 4,
        slope: float = 10,
        # SAR params
        subject_category: SubjectCategory = SubjectCategory.HIKER,
        hours_missing: float = 0,
        terrain: str = "forest",
        # Earthquake params
        earthquake: Optional[EarthquakeEvent] = None,
        # Tsunami params
        tsunami_source: Optional[TsunamiSource] = None,
        coastal_sites: Optional[list] = None,
        # Landslide params
        rainfall: Optional[RainfallInput] = None,
        rainfall_hours: float = 6.0,
        # Chemical params
        chemical_scenario: Optional[ReleaseScenario] = None,
    ) -> ConsensusMap:

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        active_models = []
        all_outputs = {}
        weather = None

        print(f"\n[BEACON] Running consensus for scenario: {scenario.upper()}")

        # Always get weather for fire scenarios
        if scenario in ["wildfire", "all"]:
            weather_data = self._get_weather(lat, lon)
            weather = weather_data.get("conditions")
            active_models.append("NOAA")
            outputs = self.run_wildfire(lat, lon, weather_data, fuel_model, slope)
            all_outputs.update(outputs)
            active_models.extend(outputs.keys())

        if scenario in ["sar", "all"] or hours_missing > 0:
            outputs = self.run_sar(lat, lon, subject_category, hours_missing, terrain)
            all_outputs.update(outputs)
            active_models.extend(outputs.keys())

        if scenario in ["earthquake", "all"] and earthquake:
            outputs = self.run_earthquake(lat, lon, earthquake)
            all_outputs.update(outputs)
            active_models.extend(outputs.keys())

        if scenario in ["tsunami", "all"] and tsunami_source and coastal_sites:
            outputs = self.run_tsunami(lat, lon, tsunami_source, coastal_sites)
            all_outputs.update(outputs)
            active_models.extend(outputs.keys())

        if scenario in ["landslide", "all"] and rainfall:
            outputs = self.run_landslide(rainfall, rainfall_hours)
            all_outputs.update(outputs)
            active_models.extend(outputs.keys())

        if scenario in ["chemical", "all"] and chemical_scenario:
            if not weather:
                weather_data = self._get_weather(lat, lon)
                weather = weather_data.get("conditions")
            atm = AtmosphericConditions(
                wind_speed_ms=weather_data["wind_speed"] / 2.237,
                wind_direction=weather_data["wind_direction"],
                stability_class="D",
                temperature_c=25,
                humidity=0.6,
                mixing_height_m=1000
            )
            outputs = self.run_chemical(chemical_scenario, atm)
            all_outputs.update(outputs)
            active_models.extend(outputs.keys())

        # Build consensus map
        zones = self.build_zones(all_outputs, lat, lon)

        return ConsensusMap(
            location_lat=lat,
            location_lon=lon,
            zones=zones,
            weather=weather,
            active_models=[m for m in active_models if m],
            timestamp=timestamp,
            scenario=scenario
        )


if __name__ == "__main__":
    import argparse
    import os
 
    parser = argparse.ArgumentParser(description="Beacon Consensus Engine")
    parser.add_argument(
        "--scenario", "-s",
        default=os.environ.get("BEACON_SCENARIO", "wildfire"),
        choices=["wildfire", "earthquake", "search", "chemical",
                 "flood", "landslide", "tsunami", "all"],
    )
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    args = parser.parse_args()
 
    # Default coordinates per scenario
    DEFAULTS = {
        "wildfire":   (40.1,   -121.4),
        "earthquake": (34.05,  -118.25),
        "search":     (37.86,  -119.54),
        "chemical":   (29.38,   -94.90),
        "flood":      (29.75,   -95.37),
        "landslide":  (37.20,  -121.98),
        "tsunami":    (38.80,   142.37),
    }
 
    scenario = args.scenario
    default_lat, default_lon = DEFAULTS.get(scenario, (40.1, -121.4))
    lat = args.lat if args.lat is not None else default_lat
    lon = args.lon if args.lon is not None else default_lon
 
    beacon = BeaconConsensus()
    print("🔺 BEACON MULTI-MODEL CONSENSUS SYSTEM")
    print(f"Scenario: {scenario.upper()} | Location: ({lat}, {lon})\n")
 
    if scenario == "all":
        # Explicit opt-in to run all demos
        quake = EarthquakeEvent(6.8, 18.5, 31.12, -8.38, "strike_slip")
        chem  = ReleaseScenario("chlorine", ReleaseType.INSTANTANEOUS,
                                 5000, 83.3, 60, 1.0, 29.38, -94.90)
        for r in [
            beacon.run(lat=40.1, lon=-121.4, scenario="wildfire",
                       subject_category=SubjectCategory.HIKER,
                       hours_missing=3, terrain="forest", fuel_model=4, slope=20),
            beacon.run(lat=31.2, lon=-8.3, scenario="earthquake", earthquake=quake),
            beacon.run(lat=29.38, lon=-94.90, scenario="chemical", chemical_scenario=chem),
        ]:
            print(r.summary())
            print("\n" + "=" * 60)
 
    elif scenario == "wildfire":
        result = beacon.run(
            lat=lat, lon=lon, scenario="wildfire",
            subject_category=SubjectCategory.HIKER,
            hours_missing=3, terrain="forest", fuel_model=4, slope=20,
        )
        print(result.summary())
 
    elif scenario == "earthquake":
        quake = EarthquakeEvent(6.8, 10.0, lat, lon, "strike_slip")
        result = beacon.run(lat=lat, lon=lon, scenario="earthquake", earthquake=quake)
        print(result.summary())
 
    elif scenario == "search":
        result = beacon.run(
            lat=lat, lon=lon, scenario="sar",
            subject_category=SubjectCategory.HIKER,
            hours_missing=6, terrain="forest",
        )
        print(result.summary())
 
    elif scenario == "chemical":
        chem = ReleaseScenario("chlorine", ReleaseType.INSTANTANEOUS,
                               5000, 83.3, 60, 1.0, lat, lon)
        result = beacon.run(lat=lat, lon=lon, scenario="chemical", chemical_scenario=chem)
        print(result.summary())
 
    else:
        # flood / landslide / tsunami — need extra params not yet wired to CLI
        print(f"[WARNING] '{scenario}' needs additional CLI params not yet implemented.")
        print("Running wildfire at specified coordinates as fallback.")
        result = beacon.run(
            lat=lat, lon=lon, scenario="wildfire",
            subject_category=SubjectCategory.HIKER,
            hours_missing=3, terrain="mountain", fuel_model=2, slope=30,
        )
        print(result.summary())
