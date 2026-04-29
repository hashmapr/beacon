import math
import requests
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta


# ── LIVE FEEDS ───────────────────────────────────────────────────

def get_tsunami_generating_earthquakes(hours_back: int = 24) -> list:
    """Pull recent large earthquakes that could generate tsunamis."""
    end_time   = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours_back)
    params = {
        "format":       "geojson",
        "starttime":    start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime":      end_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": 6.5,   # tsunamis typically need M6.5+
        "orderby":      "magnitude",
        "limit":        20,
    }
    try:
        r = requests.get(
            "https://earthquake.usgs.gov/fdsnws/event/1/query",
            params=params, timeout=15
        )
        r.raise_for_status()
        events = []
        for f in r.json()["features"]:
            p = f["properties"]
            c = f["geometry"]["coordinates"]
            depth = c[2]
            # Tsunamigenic if shallow submarine earthquake
            is_tsunamigenic = depth < 100 and p["mag"] >= 7.0
            events.append({
                "id":        f["id"],
                "magnitude": p["mag"],
                "lat":       c[1],
                "lon":       c[0],
                "depth_km":  depth,
                "place":     p.get("place") or "Unknown",
                "time":      datetime.utcfromtimestamp(p["time"] / 1000),
                "tsunamigenic": is_tsunamigenic,
                "tsunami_flag": p.get("tsunami", 0),
            })
        tsunamigenic = [e for e in events if e["tsunamigenic"] or e["tsunami_flag"]]
        print(f"[USGS] Found {len(events)} M6.5+ events, {len(tsunamigenic)} potentially tsunamigenic")
        return events
    except Exception as e:
        print(f"[USGS] Tsunami earthquake feed error: {e}")
        return []


def get_active_tsunami_warnings() -> list:
    """Check NOAA Pacific Tsunami Warning Center for active warnings."""
    warnings = []
    urls = [
        "https://www.tsunami.gov/events/xml/PHEBulletin.xml",
        "https://www.tsunami.gov/events/xml/ATWCBulletin.xml"
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                content = r.text
                for keyword in ["WARNING", "WATCH", "ADVISORY"]:
                    if keyword in content:
                        warnings.append({
                            "status":  keyword,
                            "source":  url,
                            "content": content[:500]
                        })
                        break
        except Exception as e:
            print(f"[NOAA] Tsunami warning fetch error: {e}")
    return warnings


def get_dart_buoy_readings(buoy_ids: List[str] = None) -> dict:
    """
    Pull DART buoy ocean pressure data from NOAA NDBC.
    DART = Deep-ocean Assessment and Reporting of Tsunamis.
    Normal ocean column height ~4000-6000m. Anomaly = tsunami wave.
    """
    if not buoy_ids:
        buoy_ids = ["21413", "21418", "21419", "46408", "46411",
                   "32412", "32413", "43412", "51407", "52402"]

    results = {}
    for buoy_id in buoy_ids:
        try:
            url = f"https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.dart"
            r   = requests.get(url, timeout=8)
            if r.status_code == 200:
                for line in r.text.strip().split("\n"):
                    if line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 6:
                        try:
                            height = float(parts[5])
                            results[buoy_id] = {
                                "water_column_m": height,
                                "status": "normal",
                                "timestamp": f"{parts[0]}-{parts[1]}-{parts[2]}T{parts[3]}:{parts[4]}"
                            }
                            break
                        except:
                            continue
        except Exception as e:
            results[buoy_id] = {"error": str(e)}

    active = {k: v for k, v in results.items()
              if isinstance(v, dict) and "water_column_m" in v}
    print(f"[DART] {len(active)}/{len(buoy_ids)} buoys responding")
    return results


# ── MOST MODEL ───────────────────────────────────────────────────

@dataclass
class TsunamiSource:
    magnitude: float
    epicenter_lat: float
    epicenter_lon: float
    depth_km: float
    fault_length_km: float
    fault_width_km: float
    fault_strike: float
    fault_dip: float
    rake: float
    slip_m: float
    place: str = "Unknown"
    live: bool = False

    @classmethod
    def from_magnitude(cls, magnitude: float, lat: float, lon: float,
                       depth: float = 10.0, fault_type: str = "reverse",
                       place: str = "Unknown", live: bool = False):
        log_L = 0.69 * magnitude - 3.22
        log_W = 0.27 * magnitude - 0.63
        log_s = 0.82 * magnitude - 4.46
        L, W, slip = 10**log_L, 10**log_W, 10**log_s
        if fault_type == "reverse":    strike, dip, rake = 0, 15, 90
        elif fault_type == "normal":   strike, dip, rake = 0, 60, -90
        else:                          strike, dip, rake = 0, 90, 0
        return cls(magnitude, lat, lon, depth, L, W, strike, dip, rake, slip, place, live)

    @classmethod
    def from_live_event(cls, quake: dict) -> "TsunamiSource":
        fault = quake.get("fault_type", "reverse")
        return cls.from_magnitude(
            quake["magnitude"], quake["lat"], quake["lon"],
            quake["depth_km"], fault, quake.get("place", "Unknown"), live=True
        )


@dataclass
class CoastalSite:
    name: str
    lat: float
    lon: float
    ocean_depth_m: float
    coastal_slope: float
    population: int
    elevation_m: float
    has_seawall: bool
    seawall_height_m: float


@dataclass
class TsunamiImpact:
    site: CoastalSite
    source: TsunamiSource
    travel_time_min: float
    wave_height_m: float
    runup_height_m: float
    inundation_distance_m: float
    arrival_speed_ms: float
    threat_level: str
    evacuation_time_min: float
    people_at_risk: int
    warning_issued: bool
    dart_confirmation: bool

    def summary(self):
        hrs  = int(self.travel_time_min // 60)
        mins = int(self.travel_time_min % 60)
        return (
            f"Source:              M{self.source.magnitude} — {self.source.place}"
            f" {'[LIVE]' if self.source.live else ''}\n"
            f"Travel Time:         {hrs}h {mins}min\n"
            f"Open Ocean Height:   {self.wave_height_m:.2f}m\n"
            f"Runup Height:        {self.runup_height_m:.1f}m\n"
            f"Inundation:          {self.inundation_distance_m:.0f}m inland\n"
            f"Wave Speed:          {self.arrival_speed_ms*3.6:.0f}km/h\n"
            f"Evacuation Window:   {self.evacuation_time_min:.0f}min\n"
            f"People at Risk:      {self.people_at_risk:,}\n"
            f"DART Confirmation:   {'YES' if self.dart_confirmation else 'Pending'}\n"
            f"Threat Level:        {self.threat_level.upper()}"
        )


class MOSTModel:
    """
    NOAA MOST — Method of Splitting Tsunamis.
    Pulls live USGS earthquake data and DART buoy readings automatically.

    Reference: Titov & Synolakis 1998.
    """

    GRAVITY = 9.81

    def _initial_wave_height(self, source: TsunamiSource) -> float:
        dip_rad  = math.radians(source.fault_dip)
        rake_rad = math.radians(source.rake)
        delta_u  = source.slip_m * math.sin(dip_rad) * math.sin(rake_rad)
        mag_scale = 10**((source.magnitude - 8.0) * 0.5)
        eta_0 = abs(delta_u) * (1 - math.exp(-source.fault_length_km * source.fault_width_km / 50000))
        return max(0.05, min(eta_0 * mag_scale, 2.0))

    def _travel_time(self, source: TsunamiSource, site: CoastalSite) -> float:
        R  = 6371000
        d  = lambda x: math.radians(x)
        a  = (math.sin(d(site.lat - source.epicenter_lat)/2)**2 +
              math.cos(d(source.epicenter_lat)) * math.cos(d(site.lat)) *
              math.sin(d(site.lon - source.epicenter_lon)/2)**2)
        dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        speed = math.sqrt(self.GRAVITY * max(site.ocean_depth_m, 1.0))
        return (dist / speed) / 60

    def _shoaling(self, ocean_depth: float) -> float:
        return min((ocean_depth / 10.0)**0.25, 2.0)

    def _runup(self, wave_height_m: float, site: CoastalSite) -> float:
        beta = math.radians(max(site.coastal_slope, 0.5))
        amp  = min(2.0 / math.tan(beta), 8.0)
        runup = wave_height_m * amp
        if site.has_seawall:
            runup = max(0, runup - site.seawall_height_m * 0.7)
        return max(wave_height_m, runup)

    def _inundation(self, runup_m: float, site: CoastalSite) -> float:
        if site.coastal_slope <= 0:
            return runup_m * 500
        return max(0, (runup_m - site.elevation_m) / math.tan(math.radians(site.coastal_slope)))

    def _threat(self, runup: float, inundation: float, people: int) -> str:
        if runup > 5.0 or inundation > 500 or people > 10000: return "critical"
        elif runup > 2.0 or inundation > 200 or people > 1000: return "high"
        elif runup > 0.5 or inundation > 50:                   return "medium"
        return "low"

    def calculate(self, source: TsunamiSource, site: CoastalSite,
                  dart_data: dict = None) -> TsunamiImpact:
        eta_0      = self._initial_wave_height(source)
        travel_min = self._travel_time(source, site)
        K_s        = self._shoaling(site.ocean_depth_m)
        wave_h     = eta_0 * K_s
        runup      = self._runup(wave_h, site)
        inundation = self._inundation(runup, site)
        people     = int(site.population * min(inundation / 500, 1.0))
        evac_window = max(0, travel_min - 10)
        threat     = self._threat(runup, inundation, people)
        c_coast    = math.sqrt(self.GRAVITY * 20.0)

        # Check DART buoy confirmation
        dart_confirmed = False
        if dart_data:
            for buoy_id, reading in dart_data.items():
                if isinstance(reading, dict) and reading.get("status") == "anomaly":
                    dart_confirmed = True
                    break

        return TsunamiImpact(
            site=site, source=source,
            travel_time_min=travel_min,
            wave_height_m=wave_h,
            runup_height_m=runup,
            inundation_distance_m=inundation,
            arrival_speed_ms=c_coast,
            threat_level=threat,
            evacuation_time_min=evac_window,
            people_at_risk=people,
            warning_issued=travel_min > 20,
            dart_confirmation=dart_confirmed
        )

    def regional_assessment(self, source: TsunamiSource, sites: List[CoastalSite],
                            dart_data: dict = None) -> List[TsunamiImpact]:
        results = [self.calculate(source, site, dart_data) for site in sites]
        return sorted(results, key=lambda x: x.travel_time_min)

    def calculate_live(self, sites: List[CoastalSite]) -> List[TsunamiImpact]:
        """
        Auto-fetch latest tsunamigenic earthquakes and DART buoy data,
        then calculate impact at all coastal sites.
        """
        print("[MOST] Fetching live tsunami-generating earthquakes...")
        quakes = get_tsunami_generating_earthquakes(hours_back=48)

        print("[MOST] Fetching DART buoy readings...")
        dart = get_dart_buoy_readings()

        print("[MOST] Checking active tsunami warnings...")
        warnings = get_active_tsunami_warnings()
        if warnings:
            print(f"[MOST] ⚠️  ACTIVE TSUNAMI WARNINGS: {[w['status'] for w in warnings]}")
        else:
            print("[MOST] No active tsunami warnings.")

        if not quakes:
            print("[MOST] No significant earthquakes detected.")
            return []

        largest = max(quakes, key=lambda q: q["magnitude"])
        print(f"[MOST] Running on M{largest['magnitude']} — {largest['place']}")
        source = TsunamiSource.from_live_event(largest)
        return self.regional_assessment(source, sites, dart)

    def beacon_priority_zones(self, source: TsunamiSource,
                              sites: List[CoastalSite], dart_data: dict = None) -> dict:
        impacts = self.regional_assessment(source, sites, dart_data)
        zones   = {"red": [], "orange": [], "yellow": []}
        for imp in impacts:
            color = {"critical": "red", "high": "orange"}.get(imp.threat_level, "yellow")
            zones[color].append({
                "site":                 imp.site.name,
                "arrival_min":          imp.travel_time_min,
                "runup_m":              imp.runup_height_m,
                "people":               imp.people_at_risk,
                "evacuation_window_min":imp.evacuation_time_min,
                "dart_confirmed":       imp.dart_confirmation,
                "deploy":               "drone"
            })
        return zones


if __name__ == "__main__":
    model = MOSTModel()
    print("🌊 NOAA MOST — Live USGS + DART Buoy Integration\n")

    # Pacific coastal sites for live assessment
    pacific_sites = [
        CoastalSite("Honolulu HI",     21.31, -157.86, 4000, 8,  400000, 30, True, 3),
        CoastalSite("Crescent City CA", 41.75, -124.20, 1500, 5, 7000,   10, False, 0),
        CoastalSite("Hilo HI",         19.73, -155.09, 3000, 6, 45000,  15, True, 2),
        CoastalSite("Astoria OR",      46.19, -123.83, 1200, 4, 10000,   8, False, 0),
        CoastalSite("Seaside OR",      45.99, -123.92, 1100, 2, 6500,    5, False, 0),
    ]

    print("=" * 55)
    print("LIVE MODE — Latest Tsunamigenic Earthquakes + DART")
    print("=" * 55)
    live_results = model.calculate_live(pacific_sites)
    if live_results:
        for impact in live_results:
            print(f"\n📍 {impact.site.name}")
            print(impact.summary())
    else:
        print("No active tsunamigenic threats detected.")

    # Manual scenario
    print(f"\n{'='*55}")
    print("MANUAL: 2004 Indian Ocean M9.1")
    print(f"{'='*55}")
    source_2004 = TsunamiSource(
        magnitude=9.1, epicenter_lat=3.30, epicenter_lon=95.78,
        depth_km=30.0, fault_length_km=1300, fault_width_km=150,
        fault_strike=340, fault_dip=8, rake=90, slip_m=15.0,
        place="Off Coast of Sumatra, Indonesia"
    )
    indian_sites = [
        CoastalSite("Banda Aceh Indonesia", 5.55, 95.32, 1000, 2, 300000, 3, False, 0),
        CoastalSite("Phuket Thailand",      7.88, 98.40, 2000, 3, 150000, 5, False, 0),
        CoastalSite("Colombo Sri Lanka",    6.93, 79.85, 3500, 2, 800000, 4, False, 0),
    ]
    for impact in model.regional_assessment(source_2004, indian_sites):
        print(f"\n📍 {impact.site.name}")
        print(impact.summary())