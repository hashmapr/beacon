import math
from dataclasses import dataclass
from typing import Dict, List
from shakemap import ShakeMap, EarthquakeEvent

@dataclass
class PAGERResult:
    magnitude: float
    depth_km: float
    epicenter_lat: float
    epicenter_lon: float
    fatality_estimate_low: int
    fatality_estimate_mid: int
    fatality_estimate_high: int
    economic_loss_low_musd: float
    economic_loss_mid_musd: float
    economic_loss_high_musd: float
    alert_level: str         # green, yellow, orange, red
    affected_population: int
    countries_affected: List[str]
    threat_level: str

    def summary(self):
        return (
            f"Alert Level:     {self.alert_level.upper()}\n"
            f"Fatalities:      {self.fatality_estimate_low:,} — "
            f"{self.fatality_estimate_high:,} "
            f"(mid: {self.fatality_estimate_mid:,})\n"
            f"Economic Loss:   ${self.economic_loss_low_musd:.0f}M — "
            f"${self.economic_loss_high_musd:.0f}M USD\n"
            f"Affected Pop:    {self.affected_population:,}\n"
            f"Threat Level:    {self.threat_level.upper()}"
        )

# Vulnerability classes by region
# Based on PAGER semi-empirical fatality model
# Fatality rate per unit MMI at exposure population
VULNERABILITY = {
    "developed":    {"theta": 16.0, "beta": 0.15},
    "moderate":     {"theta": 14.0, "beta": 0.20},
    "developing":   {"theta": 13.0, "beta": 0.25},
    "vulnerable":   {"theta": 12.0, "beta": 0.30},
}

# Regional population exposure estimates (millions within 100km)
REGION_PROFILES = {
    "morocco":      {"pop": 2.0,  "vuln": "vulnerable",  "gdp_per_cap": 3500},
    "new_zealand":  {"pop": 1.5,  "vuln": "developed",   "gdp_per_cap": 42000},
    "dallas_tx":    {"pop": 7.0,  "vuln": "developed",   "gdp_per_cap": 65000},
    "nepal":        {"pop": 3.0,  "vuln": "vulnerable",  "gdp_per_cap": 1200},
    "turkey":       {"pop": 5.0,  "vuln": "moderate",    "gdp_per_cap": 9500},
    "japan":        {"pop": 8.0,  "vuln": "developed",   "gdp_per_cap": 40000},
    "haiti":        {"pop": 3.5,  "vuln": "vulnerable",  "gdp_per_cap": 800},
    "california":   {"pop": 10.0, "vuln": "developed",   "gdp_per_cap": 75000},
    "default":      {"pop": 2.0,  "vuln": "moderate",    "gdp_per_cap": 10000},
}


class PAGERModel:
    """
    USGS PAGER — Prompt Assessment of Global Earthquakes for Response.

    Reference: Jaiswal, K. and Wald, D. 2010.
    An Empirical Model for Global Earthquake Fatality Estimation.
    Earthquake Spectra, 26(4), 1017-1037.

    Estimates fatalities within minutes of any earthquake.
    Used by USGS to prioritize international disaster response.
    """

    def __init__(self):
        self.shakemap = ShakeMap()

    def _mmi_to_fatality_rate(
        self,
        mmi: float,
        vulnerability_class: str
    ) -> float:
        """
        Lognormal fatality rate model.
        P(fatality | MMI) using empirical vulnerability function.
        """
        params = VULNERABILITY.get(vulnerability_class, VULNERABILITY["moderate"])
        theta = params["theta"]
        beta = params["beta"]

        if mmi <= 0:
            return 0.0

        # Lognormal CDF
        z = (math.log(mmi) - math.log(theta)) / beta
        fatality_rate = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        fatality_rate = max(0.0, min(fatality_rate, 0.005))

        return max(0.0, min(fatality_rate, 0.5))

    def _estimate_fatalities(
        self,
        mmi: float,
        population: int,
        vulnerability_class: str
    ) -> tuple:
        """
        Estimate fatality range from MMI and population.
        Returns (low, mid, high) estimates.
        """
        base_rate = self._mmi_to_fatality_rate(mmi, vulnerability_class)

        mid = int(population * base_rate)
        low = int(mid * 0.5)
        high = int(mid * 2.0)

        return low, mid, high

    def _estimate_economic_loss(
        self,
        mmi: float,
        population: int,
        gdp_per_capita: float
    ) -> tuple:
        """
        Estimate economic loss in millions USD.
        Based on HAZUS economic loss methodology.
        """
        # Damage ratio increases with MMI
        if mmi < 4:
            damage_ratio = 0.0
        elif mmi < 6:
            damage_ratio = 0.01
        elif mmi < 7:
            damage_ratio = 0.05
        elif mmi < 8:
            damage_ratio = 0.15
        elif mmi < 9:
            damage_ratio = 0.35
        else:
            damage_ratio = 0.65

        # Total economic exposure
        avg_household = 4
        households = population / avg_household
        avg_home_value = gdp_per_capita * 3
        total_exposure_musd = (households * avg_home_value) / 1e6

        mid_loss = total_exposure_musd * damage_ratio
        low_loss = mid_loss * 0.3
        high_loss = mid_loss * 2.5

        return low_loss, mid_loss, high_loss

    def _alert_level(self, fatalities_mid: int, loss_mid_musd: float) -> str:
        """
        PAGER alert level based on estimated impact.
        Green < 1 fatality, Yellow < 10, Orange < 1000, Red >= 1000
        """
        if fatalities_mid >= 1000 or loss_mid_musd >= 1000:
            return "red"
        elif fatalities_mid >= 10 or loss_mid_musd >= 100:
            return "orange"
        elif fatalities_mid >= 1 or loss_mid_musd >= 10:
            return "yellow"
        return "green"

    def calculate(
        self,
        event: EarthquakeEvent,
        region: str = "default",
        custom_population: int = None,
        custom_gdp: float = None
    ) -> PAGERResult:
        """
        Run PAGER fatality and loss estimation.

        Args:
            event: Earthquake parameters
            region: Named region for vulnerability profile
            custom_population: Override population estimate
            custom_gdp: Override GDP per capita
        """
        profile = REGION_PROFILES.get(region, REGION_PROFILES["default"])

        population = custom_population or int(profile["pop"] * 1e6)
        gdp_per_cap = custom_gdp or profile["gdp_per_cap"]
        vuln_class = profile["vuln"]

        # Get ground shaking at epicenter
        shake = self.shakemap.calculate(
            event,
            event.epicenter_lat,
            event.epicenter_lon + 0.05  # slight offset to avoid zero distance
        )
        mmi = shake.mmi

        # Fatality estimate
        fat_low, fat_mid, fat_high = self._estimate_fatalities(
            mmi, population, vuln_class
        )

        # Economic loss
        loss_low, loss_mid, loss_high = self._estimate_economic_loss(
            mmi, population, gdp_per_cap
        )

        # Alert level
        alert = self._alert_level(fat_mid, loss_mid)

        # Threat level for Beacon
        if alert in ["red", "orange"]:
            threat = "critical" if alert == "red" else "high"
        elif alert == "yellow":
            threat = "medium"
        else:
            threat = "low"

        return PAGERResult(
            magnitude=event.magnitude,
            depth_km=event.depth_km,
            epicenter_lat=event.epicenter_lat,
            epicenter_lon=event.epicenter_lon,
            fatality_estimate_low=fat_low,
            fatality_estimate_mid=fat_mid,
            fatality_estimate_high=fat_high,
            economic_loss_low_musd=loss_low,
            economic_loss_mid_musd=loss_mid,
            economic_loss_high_musd=loss_high,
            alert_level=alert,
            affected_population=population,
            countries_affected=[region],
            threat_level=threat
        )

    def beacon_priority_zones(self, result: PAGERResult) -> dict:
        color_map = {"red": "red", "orange": "orange",
                    "yellow": "yellow", "green": "yellow"}
        color = color_map.get(result.alert_level, "yellow")
        return {
            color: {
                "priority": {"red": 1, "orange": 2, "yellow": 3}[color],
                "alert": result.alert_level,
                "fatalities_mid": result.fatality_estimate_mid,
                "loss_musd": result.economic_loss_mid_musd,
                "deploy": "drone",
                "label": f"PAGER {result.alert_level.upper()} — "
                         f"{result.fatality_estimate_mid:,} est. fatalities"
            }
        }


if __name__ == "__main__":
    model = PAGERModel()

    print("📊 USGS PAGER CASUALTY ESTIMATION MODEL")
    print("Prompt Assessment of Global Earthquakes for Response\n")

    scenarios = [
        ("2023 Morocco M6.8", EarthquakeEvent(6.8, 18.5, 31.12, -8.38, "strike_slip"), "morocco"),
        ("2015 Nepal M7.8", EarthquakeEvent(7.8, 15.0, 28.23, 84.73, "reverse"), "nepal"),
        ("2010 Haiti M7.0", EarthquakeEvent(7.0, 13.0, 18.44, -72.57, "strike_slip"), "haiti"),
        ("Hypothetical Dallas M6.5", EarthquakeEvent(6.5, 15.0, 32.78, -96.80, "strike_slip"), "dallas_tx"),
        ("Hypothetical California M7.5", EarthquakeEvent(7.5, 10.0, 34.05, -118.25, "strike_slip"), "california"),
    ]

    for name, event, region in scenarios:
        print(f"\n{'='*55}")
        print(f"SCENARIO: {name}")
        print(f"{'='*55}")
        result = model.calculate(event, region)
        print(result.summary())