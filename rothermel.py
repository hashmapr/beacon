import math
import requests
from dataclasses import dataclass
from typing import Optional


# ── LIVE NOAA WEATHER FEED ───────────────────────────────────────

def get_live_fire_weather(lat: float, lon: float) -> Optional[dict]:
    """Pull live weather from NOAA API. Free, no key required."""
    headers = {"User-Agent": "Beacon-Disaster-Response/1.0"}
    try:
        r = requests.get(f"https://api.weather.gov/points/{lat},{lon}",
                        headers=headers, timeout=10)
        r.raise_for_status()
        stations_url = r.json()["properties"]["observationStations"]
        r2 = requests.get(stations_url, headers=headers, timeout=10)
        station_id   = r2.json()["features"][0]["properties"]["stationIdentifier"]
        station_name = r2.json()["features"][0]["properties"]["name"]
        r3 = requests.get(
            f"https://api.weather.gov/stations/{station_id}/observations/latest",
            headers=headers, timeout=10
        )
        obs      = r3.json()["properties"]
        temp_c   = obs.get("temperature",      {}).get("value") or 20
        humidity = obs.get("relativeHumidity", {}).get("value") or 50
        wind_ms  = obs.get("windSpeed",        {}).get("value") or 0
        wind_dir = obs.get("windDirection",    {}).get("value") or 0
        temp_f   = temp_c * 9/5 + 32
        wind_mph = wind_ms * 2.237
        base     = humidity / 100.0 * 0.30
        adj      = (temp_f - 70) * 0.001
        m1hr     = max(0.01, min(0.40, base - adj))
        print(f"[NOAA] {station_id} — {station_name}")
        print(f"[NOAA] {temp_f:.1f}°F  {humidity:.0f}% RH  {wind_mph:.1f}mph @ {wind_dir:.0f}°  moisture: {m1hr*100:.1f}%")
        return {
            "wind_speed":     wind_mph,
            "wind_direction": wind_dir,
            "moisture_1hr":   m1hr,
            "moisture_10hr":  min(m1hr * 1.5, 0.40),
            "moisture_100hr": min(m1hr * 2.0, 0.40),
            "moisture_live":  min(m1hr * 4.0, 1.50),
            "temperature_f":  temp_f,
            "humidity":       humidity,
            "station":        station_id,
        }
    except Exception as e:
        print(f"[NOAA] Weather fetch error: {e}")
        return None


# ── ROTHERMEL MODEL ──────────────────────────────────────────────

CONV = 2000 / 43560

@dataclass
class FuelModel:
    name: str
    fuel_load_1hr: float
    fuel_load_10hr: float
    fuel_load_100hr: float
    fuel_load_live: float
    fuel_depth: float
    extinction_moisture: float
    sav_1hr: float

FUEL_MODELS = {
    1:  FuelModel("Short Grass",     0.74*CONV, 0.00,      0.00,      0.00,      1.0, 0.12, 3500),
    2:  FuelModel("Timber Grass",    2.00*CONV, 1.00*CONV, 0.50*CONV, 0.50*CONV, 1.0, 0.15, 3000),
    3:  FuelModel("Tall Grass",      3.01*CONV, 0.00,      0.00,      0.00,      2.5, 0.25, 1500),
    4:  FuelModel("Chaparral",       5.01*CONV, 4.01*CONV, 2.00*CONV, 5.01*CONV, 6.0, 0.20, 2000),
    5:  FuelModel("Brush",           1.00*CONV, 0.50*CONV, 0.00,      2.00*CONV, 2.0, 0.20, 2000),
    6:  FuelModel("Dormant Brush",   1.50*CONV, 2.50*CONV, 2.00*CONV, 0.00,      2.5, 0.25, 1750),
    7:  FuelModel("Southern Rough",  1.13*CONV, 1.87*CONV, 1.50*CONV, 0.37*CONV, 2.5, 0.40, 1750),
    8:  FuelModel("Compact Timber",  1.50*CONV, 1.00*CONV, 2.50*CONV, 0.00,      0.2, 0.30, 2000),
    9:  FuelModel("Hardwood Litter", 2.92*CONV, 0.41*CONV, 0.15*CONV, 0.00,      0.2, 0.25, 2500),
    10: FuelModel("Timber Litter",   3.01*CONV, 2.00*CONV, 5.01*CONV, 2.00*CONV, 1.0, 0.25, 2000),
    11: FuelModel("Light Slash",     1.50*CONV, 3.50*CONV, 5.30*CONV, 0.00,      1.0, 0.15, 1500),
    12: FuelModel("Medium Slash",    4.01*CONV, 14.0*CONV, 16.5*CONV, 0.00,      2.3, 0.20, 1500),
    13: FuelModel("Heavy Slash",     7.01*CONV, 23.0*CONV, 28.0*CONV, 0.00,      3.0, 0.25, 1500),
}

@dataclass
class FireEnvironment:
    fuel_model: int
    wind_speed: float
    wind_direction: float
    slope: float
    aspect: float
    moisture_1hr: float
    moisture_10hr: float
    moisture_100hr: float
    moisture_live: float

@dataclass
class FireBehavior:
    spread_rate_fpm: float
    spread_rate_mph: float
    spread_rate_mpm: float
    intensity: float
    flame_length: float
    direction: float

    def summary(self):
        chains_hr = self.spread_rate_fpm * 60 / 66
        return (
            f"Rate of Spread: {chains_hr:.1f} ch/hr ({self.spread_rate_mph:.2f} mph)\n"
            f"Flame Length:   {self.flame_length:.1f} ft\n"
            f"Intensity:      {self.intensity:.0f} BTU/ft/s\n"
            f"Direction:      {self.direction:.0f}°"
        )


class RothermelModel:
    """
    Rothermel 1972 Surface Fire Spread Model.
    Pulls live NOAA weather automatically via calculate_live().
    Reference: USDA Forest Service INT-115.
    """

    def calculate(self, env: FireEnvironment) -> FireBehavior:
        fuel = FUEL_MODELS.get(env.fuel_model)
        if not fuel:
            raise ValueError(f"Unknown fuel model: {env.fuel_model}")

        w_d   = fuel.fuel_load_1hr + fuel.fuel_load_10hr + fuel.fuel_load_100hr
        w_n   = w_d * (1.0 - 0.0555)
        rho_b = w_d / fuel.fuel_depth if fuel.fuel_depth > 0 else 0.001
        beta  = max(rho_b / 32.0, 1e-6)
        sigma = fuel.sav_1hr

        beta_op  = 3.348 * sigma**(-0.8189)
        gamma_max = sigma**1.5 / (495.0 + 0.0594 * sigma**1.5)
        A        = 133.0 * sigma**(-0.7913)
        beta_r   = beta / beta_op
        gamma_op = gamma_max * (beta_r**A) * math.exp(A * (1.0 - beta_r))

        r_M   = min(env.moisture_1hr / fuel.extinction_moisture, 1.0)
        eta_M = max(1.0 - 2.59*r_M + 5.11*r_M**2 - 3.52*r_M**3, 0.0)
        eta_s = 0.174 * (0.01)**(-0.19)
        I_R   = gamma_op * w_n * 8000.0 * eta_M * eta_s

        xi = math.exp((0.792 + 0.681 * sigma**0.5) * (beta + 0.1)) / (192.0 + 0.2595 * sigma)

        U     = min(env.wind_speed * 0.4 * 88.0, 300.0)
        B     = 0.02526 * sigma**0.54
        C     = 7.47   * math.exp(-0.133 * sigma**0.55)
        E     = 0.715  * math.exp(-3.59e-4 * sigma)
        if U > 0.9 * I_R:
            U = 0.9 * I_R
        phi_w = C * (U**B) * (beta**(-E))
        phi_s = 5.275 * (beta**(-0.3)) * (env.slope / 100.0)**2

        heat_sink = rho_b * (250.0 + 1116.0 * env.moisture_1hr)
        R         = (I_R * xi * (1.0 + phi_w + phi_s)) / max(heat_sink, 0.001)
        I_B       = (I_R * fuel.fuel_depth * R) / 60.0 / 10.0
        L         = 0.45 * I_B**0.46 if I_B > 0 else 0.0

        return FireBehavior(
            spread_rate_fpm=R,
            spread_rate_mph=R * 60.0 / 5280.0,
            spread_rate_mpm=R * 0.3048,
            intensity=I_B,
            flame_length=L,
            direction=(env.wind_direction + 180.0) % 360.0
        )

    def calculate_live(self, lat: float, lon: float,
                       fuel_model: int = 4, slope: float = 10,
                       aspect: float = 180) -> Optional[FireBehavior]:
        """Pull live NOAA weather and run Rothermel. No manual input needed."""
        print(f"[ROTHERMEL] Fetching live weather for ({lat}, {lon})...")
        w = get_live_fire_weather(lat, lon)
        if not w:
            return None
        env = FireEnvironment(
            fuel_model=fuel_model,
            wind_speed=w["wind_speed"], wind_direction=w["wind_direction"],
            slope=slope, aspect=aspect,
            moisture_1hr=w["moisture_1hr"], moisture_10hr=w["moisture_10hr"],
            moisture_100hr=w["moisture_100hr"], moisture_live=w["moisture_live"]
        )
        return self.calculate(env)

    def threat_level(self, b: FireBehavior) -> str:
        if b.spread_rate_mph > 3.0 or b.flame_length > 15.0:  return "critical"
        elif b.spread_rate_mph > 1.0 or b.flame_length > 8.0: return "high"
        elif b.spread_rate_mph > 0.2 or b.flame_length > 2.0: return "medium"
        return "low"


if __name__ == "__main__":
    model = RothermelModel()
    print("🔥 ROTHERMEL 1972 — Live NOAA Weather Integration\n")

    locations = [
        ("Plumas County CA", 40.1, -121.4, 4, 20),
        ("Allen TX",         33.1,  -96.6, 1,  5),
        ("Los Angeles CA",  34.05,-118.25, 4, 15),
    ]

    for name, lat, lon, fuel, slope in locations:
        print(f"\n{'='*55}")
        print(f"LOCATION: {name}  |  Fuel: {FUEL_MODELS[fuel].name}  |  Slope: {slope}%")
        print(f"{'='*55}")
        result = model.calculate_live(lat, lon, fuel_model=fuel, slope=slope)
        if result:
            print(result.summary())
            print(f"Threat Level: {model.threat_level(result).upper()}")