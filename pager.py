import math
import requests
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from shakemap import ShakeMap, EarthquakeEvent, get_largest_nearby_quake


VULNERABILITY = {
    "developed":  {"theta": 16.0, "beta": 0.15},
    "moderate":   {"theta": 14.0, "beta": 0.20},
    "developing": {"theta": 13.0, "beta": 0.25},
    "vulnerable": {"theta": 12.0, "beta": 0.30},
}

REGION_PROFILES = {
    "morocco":       {"pop": 2.0,  "vuln": "vulnerable",  "gdp": 3500},
    "new_zealand":   {"pop": 1.5,  "vuln": "developed",   "gdp": 42000},
    "dallas_tx":     {"pop": 7.0,  "vuln": "developed",   "gdp": 65000},
    "nepal":         {"pop": 3.0,  "vuln": "vulnerable",  "gdp": 1200},
    "turkey":        {"pop": 5.0,  "vuln": "moderate",    "gdp": 9500},
    "japan":         {"pop": 8.0,  "vuln": "developed",   "gdp": 40000},
    "haiti":         {"pop": 3.5,  "vuln": "vulnerable",  "gdp": 800},
    "california":    {"pop": 10.0, "vuln": "developed",   "gdp": 75000},
    "anchorage_ak":  {"pop": 0.4,  "vuln": "developed",   "gdp": 55000},
    "seattle_wa":    {"pop": 4.0,  "vuln": "developed",   "gdp": 72000},
    "salt_lake_ut":  {"pop": 1.2,  "vuln": "developed",   "gdp": 52000},
    "default":       {"pop": 2.0,  "vuln": "moderate",    "gdp": 10000},
}

# Lat/lon bounds for auto region detection
REGION_BOUNDS = {
    "california":   (32.5, 42.0, -124.5, -114.0),
    "anchorage_ak": (59.0, 65.0, -155.0, -145.0),
    "seattle_wa":   (46.0, 49.0, -125.0, -120.0),
    "japan":        (30.0, 46.0, 128.0, 148.0),
    "nepal":        (26.0, 30.5, 80.0, 89.0),
    "turkey":       (36.0, 42.0, 26.0, 45.0),
    "new_zealand":  (-48.0, -34.0, 165.0, 179.0),
    "morocco":      (27.0, 36.0, -14.0, -1.0),
    "haiti":        (17.5, 20.5, -74.5, -71.0),
}


def detect_region(lat: float, lon: float) -> str:
    """Auto-detect region from coordinates."""
    for region, (lat_min, lat_max, lon_min, lon_max) in REGION_BOUNDS.items():
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return region
    return "default"


@dataclass
class PAGERResult:
    magnitude: float
    depth_km: float
    epicenter_lat: float
    epicenter_lon: float
    place: str
    fatality_low: int
    fatality_mid: int
    fatality_high: int
    loss_low_musd: float
    loss_mid_musd: float
    loss_high_musd: float
    alert_level: str
    affected_population: int
    region: str
    threat_level: str
    live_data: bool

    def summary(self):
        return (
            f"Source:          {'LIVE USGS' if self.live_data else 'Manual'}\n"
            f"Event:           M{self.magnitude} — {self.place}\n"
            f"Region:          {self.region}\n"
            f"Alert Level:     {self.alert_level.upper()}\n"
            f"Fatalities:      {self.fatality_low:,} — {self.fatality_high:,} "
            f"(mid: {self.fatality_mid:,})\n"
            f"Economic Loss:   ${self.loss_low_musd:.0f}M — ${self.loss_high_musd:.0f}M USD\n"
            f"Affected Pop:    {self.affected_population:,}\n"
            f"Threat Level:    {self.threat_level.upper()}"
        )


class PAGERModel:
    """
    USGS PAGER — Prompt Assessment of Global Earthquakes.
    Automatically fetches live earthquake data from USGS ComCat.

    Reference: Jaiswal & Wald 2010. Earthquake Spectra 26(4).
    """

    def __init__(self):
        self.shakemap = ShakeMap()

    def _fatality_rate(self, mmi: float, vuln_class: str) -> float:
        p = VULNERABILITY.get(vuln_class, VULNERABILITY["moderate"])
        if mmi <= 0: return 0.0
        z = (math.log(mmi) - math.log(p["theta"])) / p["beta"]
        rate = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        return max(0.0, min(rate, 0.005))

    def _fatalities(self, mmi: float, population: int, vuln: str) -> tuple:
        rate = self._fatality_rate(mmi, vuln)
        mid  = int(population * rate)
        return int(mid * 0.5), mid, int(mid * 2.0)

    def _economic_loss(self, mmi: float, population: int, gdp: float) -> tuple:
        if mmi < 4:        damage = 0.0
        elif mmi < 6:      damage = 0.01
        elif mmi < 7:      damage = 0.05
        elif mmi < 8:      damage = 0.15
        elif mmi < 9:      damage = 0.35
        else:              damage = 0.65
        exposure = (population / 4) * (gdp * 3) / 1e6
        mid = exposure * damage
        return mid * 0.3, mid, mid * 2.5

    def _alert_level(self, fat_mid: int, loss_mid: float) -> str:
        if fat_mid >= 1000 or loss_mid >= 1000: return "red"
        elif fat_mid >= 10 or loss_mid >= 100:  return "orange"
        elif fat_mid >= 1  or loss_mid >= 10:   return "yellow"
        return "green"

    def calculate(self, event: EarthquakeEvent, region: str = "default",
                  population: int = None, gdp: float = None,
                  live_data: bool = False, place: str = "Unknown") -> PAGERResult:
        profile = REGION_PROFILES.get(region, REGION_PROFILES["default"])
        pop     = population or int(profile["pop"] * 1e6)
        gdp_cap = gdp or profile["gdp"]
        vuln    = profile["vuln"]

        shake   = self.shakemap.calculate(
            event,
            event.epicenter_lat,
            event.epicenter_lon + 0.05
        )
        mmi = shake.mmi

        f_low, f_mid, f_high = self._fatalities(mmi, pop, vuln)
        l_low, l_mid, l_high = self._economic_loss(mmi, pop, gdp_cap)
        alert   = self._alert_level(f_mid, l_mid)
        threat  = {"red": "critical", "orange": "high",
                  "yellow": "medium", "green": "low"}[alert]

        return PAGERResult(
            magnitude=event.magnitude,
            depth_km=event.depth_km,
            epicenter_lat=event.epicenter_lat,
            epicenter_lon=event.epicenter_lon,
            place=place,
            fatality_low=f_low, fatality_mid=f_mid, fatality_high=f_high,
            loss_low_musd=l_low, loss_mid_musd=l_mid, loss_high_musd=l_high,
            alert_level=alert,
            affected_population=pop,
            region=region, threat_level=threat, live_data=live_data
        )

    def calculate_live(self, lat: float, lon: float,
                       radius_km: float = 500) -> Optional[PAGERResult]:
        """
        Auto-fetch largest nearby earthquake and run PAGER assessment.
        Auto-detects region from coordinates.
        """
        print(f"[PAGER] Fetching live earthquake data near ({lat}, {lon})...")
        quake = get_largest_nearby_quake(lat, lon, radius_km)
        if not quake:
            print("[PAGER] No significant earthquakes found nearby.")
            return None

        print(f"[PAGER] M{quake['magnitude']} — {quake['place']}")
        region = detect_region(quake["lat"], quake["lon"])
        print(f"[PAGER] Auto-detected region: {region}")

        event = EarthquakeEvent.from_live(quake)
        return self.calculate(event, region, live_data=True, place=quake["place"])

    def beacon_priority_zones(self, result: PAGERResult) -> dict:
        color = {"red": "red", "orange": "orange",
                "yellow": "yellow", "green": "yellow"}[result.alert_level]
        return {
            color: {
                "priority":       {"red": 1, "orange": 2, "yellow": 3}[color],
                "alert":          result.alert_level,
                "fatalities_mid": result.fatality_mid,
                "loss_musd":      result.loss_mid_musd,
                "deploy":         "drone",
                "label":          f"PAGER {result.alert_level.upper()} — "
                                  f"{result.fatality_mid:,} est. fatalities"
            }
        }


if __name__ == "__main__":
    model = PAGERModel()
    print("📊 USGS PAGER — Live Earthquake Integration\n")

    # Live mode — auto-fetch for high-risk zones
    locations = [
        ("Los Angeles CA",    34.05, -118.25),
        ("Anchorage AK",      61.22, -149.90),
        ("Seattle WA",        47.61, -122.33),
        ("Salt Lake City UT", 40.76, -111.89),
    ]

    for name, lat, lon in locations:
        print(f"\n{'='*55}")
        print(f"LOCATION: {name}")
        print(f"{'='*55}")
        result = model.calculate_live(lat, lon, radius_km=800)
        if result:
            print(result.summary())
        else:
            print("No significant seismic activity detected.")

    # Manual scenarios
    print(f"\n{'='*55}")
    print("MANUAL SCENARIOS")
    print(f"{'='*55}")
    scenarios = [
        ("2023 Morocco M6.8", EarthquakeEvent(6.8, 18.5, 31.12, -8.38, "strike_slip"), "morocco"),
        ("2015 Nepal M7.8",   EarthquakeEvent(7.8, 15.0, 28.23, 84.73, "reverse"),    "nepal"),
        ("2010 Haiti M7.0",   EarthquakeEvent(7.0, 13.0, 18.44,-72.57, "strike_slip"), "haiti"),
    ]
    for name, event, region in scenarios:
        print(f"\n{name}")
        result = model.calculate(event, region, place=name)
        print(result.summary())