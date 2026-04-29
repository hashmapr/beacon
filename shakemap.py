import math
import requests
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timedelta


# ── LIVE USGS EARTHQUAKE FEED ────────────────────────────────────

def get_recent_earthquakes(
    min_magnitude: float = 4.0,
    hours_back: int = 72,
    lat: float = None,
    lon: float = None,
    radius_km: float = 500
) -> list:
    """Pull live earthquakes from USGS ComCat API. Free, no key."""
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours_back)
    params = {
        "format": "geojson",
        "starttime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime":   end_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": min_magnitude,
        "orderby": "magnitude",
        "limit": 50,
    }
    if lat and lon:
        params["latitude"]    = lat
        params["longitude"]   = lon
        params["maxradiuskm"] = radius_km

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
            fault = "strike_slip" if depth < 20 else "reverse" if depth < 70 else "normal"
            events.append({
                "id":        f["id"],
                "magnitude": p["mag"] or 0,
                "lat":       c[1],
                "lon":       c[0],
                "depth_km":  depth,
                "place":     p.get("place") or "Unknown",
                "fault_type": fault,
                "time":      datetime.utcfromtimestamp(p["time"] / 1000),
                "url":       p.get("url") or "",
            })
        return events
    except Exception as e:
        print(f"[USGS] Feed error: {e}")
        return []


def get_largest_nearby_quake(lat: float, lon: float, radius_km: float = 500) -> Optional[dict]:
    """Get largest earthquake near a location in last 72 hours."""
    events = get_recent_earthquakes(
        min_magnitude=3.0, hours_back=72,
        lat=lat, lon=lon, radius_km=radius_km
    )
    return max(events, key=lambda e: e["magnitude"]) if events else None


# ── SHAKEMAP MODEL ───────────────────────────────────────────────

@dataclass
class EarthquakeEvent:
    magnitude: float
    depth_km: float
    epicenter_lat: float
    epicenter_lon: float
    fault_type: str

    @classmethod
    def from_live(cls, quake: dict) -> "EarthquakeEvent":
        return cls(
            magnitude=quake["magnitude"],
            depth_km=quake["depth_km"],
            epicenter_lat=quake["lat"],
            epicenter_lon=quake["lon"],
            fault_type=quake["fault_type"]
        )


@dataclass
class ShakeMapResult:
    pga: float
    pgv: float
    mmi: float
    mmi_description: str
    site_lat: float
    site_lon: float
    distance_km: float
    threat_level: str

    def summary(self):
        return (
            f"Distance from epicenter: {self.distance_km:.1f}km\n"
            f"Peak Ground Acceleration: {self.pga:.4f}g ({self.pga*980:.1f}cm/s²)\n"
            f"Peak Ground Velocity:     {self.pgv:.1f}cm/s\n"
            f"MMI Intensity:            {self.mmi:.1f} — {self.mmi_description}\n"
            f"Threat Level:             {self.threat_level.upper()}"
        )


MMI_DESC = {
    1: "Not felt", 2: "Weak", 3: "Weak", 4: "Light",
    5: "Moderate", 6: "Strong", 7: "Very Strong",
    8: "Severe", 9: "Violent", 10: "Extreme",
    11: "Extreme", 12: "Catastrophic"
}

FAULT_COEFFS = {
    "strike_slip": 0.0,
    "reverse":     0.28,
    "normal":     -0.12,
    "unknown":     0.0
}


class ShakeMap:
    """
    USGS ShakeMap — Boore-Atkinson 2008 GMPE.
    Pulls live earthquake data from USGS ComCat automatically.
    """

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        R = 6371.0
        d = lambda x: math.radians(x)
        a = (math.sin(d(lat2-lat1)/2)**2 +
             math.cos(d(lat1)) * math.cos(d(lat2)) *
             math.sin(d(lon2-lon1)/2)**2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _hypocentral_distance(self, site_lat, site_lon, event: EarthquakeEvent) -> float:
        surf = self._haversine(event.epicenter_lat, event.epicenter_lon, site_lat, site_lon)
        return math.sqrt(surf**2 + event.depth_km**2)

    def _boore_atkinson_pga(self, event: EarthquakeEvent, r_hypo: float, vs30: float = 760.0) -> float:
        M = event.magnitude
        R = max(r_hypo, 1.0)
        e1, e2, e3, e4, e5, e6, e7 = -0.53804, -0.50350, -0.75472, 0.27090, 5.00121, -0.00430, 0.0
        Mh = 6.75
        c1, c2, c3, h = -0.66050, 0.11970, -0.01151, 2.54
        blin, b1, b2 = -0.36, -0.64, -0.14
        fault_corr = FAULT_COEFFS.get(event.fault_type, 0.0)
        R_rup = math.sqrt(R**2 + h**2)
        f_dis = (c1 + c2*(M - Mh)) * math.log(R_rup) + c3 * R_rup
        if M <= Mh:
            f_mag = e1 + e2*(M-Mh) + e3*(M-Mh)**2 + e5*(M-Mh)
        else:
            f_mag = e1 + e4*(M-Mh) + e7*(M-Mh)**2
        f_site = blin * math.log(vs30/760.0) if vs30 <= 760 else 0.0
        return math.exp(f_mag + fault_corr + f_dis + f_site)

    def _pgv_from_pga(self, pga: float, magnitude: float) -> float:
        return pga * 980 * 0.1 * (1 + 0.5 * (magnitude - 6.0))

    def _pga_to_mmi(self, pga: float) -> float:
        if pga <= 0: return 1.0
        pga_cms2 = pga * 980.0
        if pga_cms2 < 0.17:   return 1.0
        elif pga_cms2 < 1.4:  mmi = 3.66 * math.log10(pga_cms2) - 1.66
        else:                  mmi = 3.47 * math.log10(pga_cms2) + 1.22
        return max(1.0, min(12.0, mmi))

    def _threat(self, mmi: float) -> str:
        if mmi >= 8: return "critical"
        elif mmi >= 6: return "high"
        elif mmi >= 4: return "medium"
        return "low"

    def calculate(self, event: EarthquakeEvent, site_lat: float, site_lon: float, vs30: float = 760.0) -> ShakeMapResult:
        r = self._hypocentral_distance(site_lat, site_lon, event)
        pga = self._boore_atkinson_pga(event, r, vs30)
        pgv = self._pgv_from_pga(pga, event.magnitude)
        mmi = self._pga_to_mmi(pga)
        mmi_int = int(min(12, max(1, round(mmi))))
        return ShakeMapResult(
            pga=pga, pgv=pgv, mmi=mmi,
            mmi_description=MMI_DESC.get(mmi_int, "Unknown"),
            site_lat=site_lat, site_lon=site_lon,
            distance_km=r, threat_level=self._threat(mmi)
        )

    def calculate_live(self, site_lat: float, site_lon: float, radius_km: float = 500) -> Optional[ShakeMapResult]:
        """Auto-fetch largest nearby earthquake and calculate shaking."""
        print(f"[SHAKEMAP] Fetching live earthquake data near ({site_lat}, {site_lon})...")
        quake = get_largest_nearby_quake(site_lat, site_lon, radius_km)
        if not quake:
            print("[SHAKEMAP] No significant earthquakes found nearby.")
            return None
        print(f"[SHAKEMAP] Found M{quake['magnitude']} — {quake['place']}")
        event = EarthquakeEvent.from_live(quake)
        return self.calculate(event, site_lat, site_lon)

    def map_region(self, event: EarthquakeEvent, center_lat: float, center_lon: float,
                   radius_km: float = 50, grid_points: int = 5) -> List[ShakeMapResult]:
        results = []
        step = (radius_km / 111.0) / grid_points
        for i in range(-grid_points, grid_points + 1):
            for j in range(-grid_points, grid_points + 1):
                results.append(self.calculate(event, center_lat + i*step, center_lon + j*step))
        return results

    def beacon_priority_zones(self, event: EarthquakeEvent, center_lat: float, center_lon: float) -> dict:
        zones = {}
        for i, (dist, color) in enumerate([(5, "red"), (20, "orange"), (50, "yellow")]):
            result = self.calculate(event, center_lat + dist/111.0, center_lon)
            zones[color] = {
                "priority": i + 1,
                "radius_km": dist,
                "pga": result.pga,
                "mmi": result.mmi,
                "threat": result.threat_level,
                "deploy": "drone" if i == 0 else "rover",
                "label": f"MMI {result.mmi:.1f} — {result.mmi_description}"
            }
        return zones


if __name__ == "__main__":
    shake = ShakeMap()

    print("🌍 USGS SHAKEMAP — Boore-Atkinson 2008 GMPE")
    print("Live earthquake data from USGS ComCat\n")

    # Live mode — fetch real earthquakes
    test_locations = [
        ("Los Angeles CA", 34.05, -118.25),
        ("Anchorage AK",   61.22, -149.90),
        ("Tokyo Japan",    35.68,  139.69),
    ]

    for name, lat, lon in test_locations:
        print(f"\n{'='*55}")
        print(f"LOCATION: {name}")
        print(f"{'='*55}")
        result = shake.calculate_live(lat, lon, radius_km=800)
        if result:
            print(result.summary())
        else:
            print("No significant seismic activity detected.")

    # Manual scenario
    print(f"\n{'='*55}")
    print("MANUAL: 2023 Morocco M6.8")
    print(f"{'='*55}")
    event = EarthquakeEvent(6.8, 18.5, 31.12, -8.38, "strike_slip")
    result = shake.calculate(event, 31.20, -8.30)
    print(result.summary())