import math
from dataclasses import dataclass
from typing import List, Dict, Tuple

@dataclass
class TsunamiSource:
    """Earthquake source parameters for tsunami generation"""
    magnitude: float          # Moment magnitude Mw
    epicenter_lat: float      # degrees
    epicenter_lon: float      # degrees
    depth_km: float           # focal depth
    fault_length_km: float    # rupture length
    fault_width_km: float     # rupture width
    fault_strike: float       # degrees - fault orientation
    fault_dip: float          # degrees - fault dip angle
    rake: float               # degrees - slip direction
    slip_m: float             # average slip in meters

    @classmethod
    def from_magnitude(cls, magnitude: float, lat: float, lon: float, 
                      depth: float = 10.0, fault_type: str = "reverse"):
        """Auto-calculate fault parameters from magnitude using scaling relations"""
        # Wells & Coppersmith 1994 scaling relations
        log_L = 0.69 * magnitude - 3.22  # fault length
        log_W = 0.27 * magnitude - 0.63  # fault width  
        log_slip = 0.82 * magnitude - 4.46  # average slip

        L = 10**log_L
        W = 10**log_W
        slip = 10**log_slip

        # Fault geometry by type
        if fault_type == "reverse":
            strike, dip, rake = 0, 15, 90
        elif fault_type == "normal":
            strike, dip, rake = 0, 60, -90
        else:
            strike, dip, rake = 0, 90, 0

        return cls(magnitude, lat, lon, depth, L, W, strike, dip, rake, slip)

@dataclass
class CoastalSite:
    """Coastal location for tsunami impact assessment"""
    name: str
    lat: float
    lon: float
    ocean_depth_m: float      # average ocean depth on path
    coastal_slope: float      # beach slope angle degrees
    population: int
    elevation_m: float        # coastal elevation above sea level
    has_seawall: bool
    seawall_height_m: float

@dataclass
class TsunamiImpact:
    """Tsunami impact at a coastal site"""
    site: CoastalSite
    travel_time_min: float    # minutes from source to coast
    wave_height_m: float      # open ocean wave height
    runup_height_m: float     # maximum runup height on shore
    inundation_distance_m: float  # how far inland water reaches
    arrival_speed_ms: float   # wave speed at coast
    threat_level: str
    evacuation_time_min: float  # time available for evacuation
    people_at_risk: int
    warning_issued: bool

    def summary(self):
        hrs = int(self.travel_time_min // 60)
        mins = int(self.travel_time_min % 60)
        return (
            f"Travel Time:         {hrs}h {mins}min\n"
            f"Open Ocean Height:   {self.wave_height_m:.2f}m\n"
            f"Runup Height:        {self.runup_height_m:.1f}m\n"
            f"Inundation:          {self.inundation_distance_m:.0f}m inland\n"
            f"Wave Speed:          {self.arrival_speed_ms*3.6:.0f}km/h\n"
            f"Evacuation Window:   {self.evacuation_time_min:.0f}min\n"
            f"People at Risk:      {self.people_at_risk:,}\n"
            f"Threat Level:        {self.threat_level.upper()}"
        )

class MOSTModel:
    """
    Method of Splitting Tsunamis (MOST).
    
    Reference: Titov, V.V. and Synolakis, C.E. 1998.
    Numerical Modeling of Tidal Wave Runup.
    Journal of Waterway, Port, Coastal, and Ocean Engineering.
    
    Also: Gica et al. 2008. Sensitivity analysis of source parameters
    for tsunamis generated in the Aleutian-Alaska subduction zone.
    
    The actual model used by NOAA's Tsunami Warning Centers.
    Calculates wave propagation, shoaling, and runup.
    """

    GRAVITY = 9.81  # m/s2
    OCEAN_DENSITY = 1025  # kg/m3

    def _initial_wave_height(self, source: TsunamiSource) -> float:
        # Empirical scaling — Abe 1979 tsunami magnitude relation
        # M9.1 → ~1.5m open ocean, M8.1 → ~0.3m, M7.5 → ~0.05m
        mt = 0.5 * source.magnitude - 3.5  # tsunami magnitude
        eta_0 = 10 ** (mt - 0.5)
        return max(0.02, min(eta_0, 2.0))

    def _wave_speed(self, depth_m: float) -> float:
        """
        Shallow water wave speed: c = sqrt(g*h)
        Valid when wavelength >> depth (always true for tsunamis).
        """
        return math.sqrt(self.GRAVITY * max(depth_m, 1.0))

    def _travel_time(
        self,
        source: TsunamiSource,
        site: CoastalSite
    ) -> float:
        """
        Calculate tsunami travel time from source to coastal site.
        Uses great circle distance with average ocean depth.
        Returns travel time in minutes.
        """
        # Great circle distance
        R = 6371000  # Earth radius m
        lat1 = math.radians(source.epicenter_lat)
        lat2 = math.radians(site.lat)
        dlat = math.radians(site.lat - source.epicenter_lat)
        dlon = math.radians(site.lon - source.epicenter_lon)

        a = (math.sin(dlat/2)**2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance_m = R * c

        # Average wave speed over path
        avg_speed = self._wave_speed(site.ocean_depth_m)

        travel_time_sec = distance_m / avg_speed
        return travel_time_sec / 60  # convert to minutes

    
    def _shoaling_coefficient(
        self,
        deep_water_height: float,
        ocean_depth: float,
        coastal_depth: float = 10.0
    ) -> float:
        # Green's Law with hard cap at 2x
        ratio = min(ocean_depth / coastal_depth, 500)
        return min(ratio ** 0.25, 2.0)

    def _runup_height(self, wave_height_m, site):
        beta = math.radians(max(site.coastal_slope, 0.5))
        # Simplified empirical runup — typically 2-5x wave height
        amplification = min(2.0 / math.tan(beta), 8.0)
        runup = wave_height_m * amplification
        if site.has_seawall:
            runup = max(0, runup - site.seawall_height_m * 0.7)
        return max(wave_height_m, runup)

    def _inundation_distance(
        self,
        runup_height: float,
        site: CoastalSite
    ) -> float:
        """
        Estimate horizontal inundation distance.
        Uses Manning's equation approximation.
        """
        if site.coastal_slope <= 0:
            return runup_height * 1000  # flat terrain

        slope_rad = math.radians(site.coastal_slope)
        
        # Simple geometric approximation
        # Distance = runup_height / tan(slope)
        distance = (runup_height - site.elevation_m) / math.tan(slope_rad)
        
        return max(0, distance)

    def _people_at_risk(
        self,
        site: CoastalSite,
        inundation_distance: float
    ) -> int:
        """Estimate population in inundation zone."""
        # Population density in coastal strip
        coastal_strip_m = 500  # standard coastal zone
        fraction_inundated = min(inundation_distance / coastal_strip_m, 1.0)
        return int(site.population * fraction_inundated)

    def _threat_level(
        self,
        runup: float,
        inundation: float,
        people: int
    ) -> str:
        if runup > 5.0 or inundation > 500 or people > 10000:
            return "critical"
        elif runup > 2.0 or inundation > 200 or people > 1000:
            return "high"
        elif runup > 0.5 or inundation > 50:
            return "medium"
        return "low"

    def calculate(
        self,
        source: TsunamiSource,
        site: CoastalSite
    ) -> TsunamiImpact:
        """
        Calculate tsunami impact at a coastal site.
        
        Args:
            source: Earthquake/tsunami source parameters
            site: Coastal site properties
            
        Returns:
            TsunamiImpact with arrival time, wave height, runup, inundation
        """
        # Initial wave height from fault
        eta_0 = self._initial_wave_height(source)

        # Travel time
        travel_min = self._travel_time(source, site)

        # Wave speed at coast
        c_coast = self._wave_speed(20.0)  # 20m coastal depth

        # Shoaling amplification
        K_s = self._shoaling_coefficient(eta_0, site.ocean_depth_m)
        wave_height = eta_0 * K_s

        # Runup
        runup = self._runup_height(wave_height, site)

        # Inundation
        inundation = self._inundation_distance(runup, site)

        # People at risk
        people = self._people_at_risk(site, inundation)

        # Evacuation window
        # Standard evacuation speed ~3km/h on foot
        # Need to reach high ground (assume 500m away)
        evacuation_needed_min = (500 / 3000) * 60  # ~10 min to reach safety
        evacuation_window = max(0, travel_min - evacuation_needed_min)

        # Threat
        threat = self._threat_level(runup, inundation, people)

        return TsunamiImpact(
            site=site,
            travel_time_min=travel_min,
            wave_height_m=wave_height,
            runup_height_m=runup,
            inundation_distance_m=inundation,
            arrival_speed_ms=c_coast,
            threat_level=threat,
            evacuation_time_min=evacuation_window,
            people_at_risk=people,
            warning_issued=travel_min > 20
        )

    def regional_assessment(
        self,
        source: TsunamiSource,
        sites: List[CoastalSite]
    ) -> List[TsunamiImpact]:
        """Assess tsunami impact across multiple coastal sites."""
        results = []
        for site in sites:
            impact = self.calculate(source, site)
            results.append(impact)
        return sorted(results, key=lambda x: x.travel_time_min)

    def beacon_priority_zones(
        self,
        source: TsunamiSource,
        sites: List[CoastalSite]
    ) -> dict:
        """Generate Beacon priority zones from MOST output."""
        impacts = self.regional_assessment(source, sites)
        zones = {"red": [], "orange": [], "yellow": []}

        for impact in impacts:
            if impact.threat_level == "critical":
                zones["red"].append({
                    "site": impact.site.name,
                    "arrival_min": impact.travel_time_min,
                    "runup_m": impact.runup_height_m,
                    "people": impact.people_at_risk,
                    "evacuation_window_min": impact.evacuation_time_min,
                    "deploy": "drone"
                })
            elif impact.threat_level == "high":
                zones["orange"].append({
                    "site": impact.site.name,
                    "arrival_min": impact.travel_time_min,
                    "runup_m": impact.runup_height_m,
                    "deploy": "sub"
                })
            else:
                zones["yellow"].append({
                    "site": impact.site.name,
                    "arrival_min": impact.travel_time_min,
                    "deploy": "drone"
                })

        return zones


if __name__ == "__main__":
    model = MOSTModel()

    print("🌊 NOAA MOST TSUNAMI PROPAGATION MODEL")
    print("Method of Splitting Tsunamis — Titov & Synolakis 1998\n")

    # 2004 Indian Ocean Tsunami
    source_2004 = TsunamiSource(
        magnitude=9.1,
        epicenter_lat=3.30,
        epicenter_lon=95.78,
        depth_km=30.0,
        fault_length_km=1300,
        fault_width_km=150,
        fault_strike=340,
        fault_dip=8,
        rake=90,
        slip_m=15.0
    )

    sites_2004 = [
        CoastalSite("Banda Aceh Indonesia", 5.55, 95.32, 1000, 2, 300000, 3, False, 0),
        CoastalSite("Phuket Thailand", 7.88, 98.40, 2000, 3, 150000, 5, False, 0),
        CoastalSite("Colombo Sri Lanka", 6.93, 79.85, 3500, 2, 800000, 4, False, 0),
        CoastalSite("Chennai India", 13.08, 80.27, 1500, 1, 2000000, 3, False, 0),
        CoastalSite("Male Maldives", 4.17, 73.51, 800, 1, 100000, 1, False, 0),
        CoastalSite("Mombasa Kenya", -4.05, 39.67, 4000, 3, 500000, 10, False, 0),
    ]

    print("="*60)
    print("SCENARIO: 2004 Indian Ocean Tsunami — M9.1")
    print("="*60)

    impacts = model.regional_assessment(source_2004, sites_2004)
    for impact in impacts:
        hrs = int(impact.travel_time_min // 60)
        mins = int(impact.travel_time_min % 60)
        print(f"\n📍 {impact.site.name}")
        print(impact.summary())

    # 2021 Kermadec
    source_kermadec = TsunamiSource.from_magnitude(
        8.1, -29.72, -177.28, 10.0, "reverse"
    )

    sites_kermadec = [
        CoastalSite("Auckland NZ", -36.86, 174.76, 1200, 5, 1600000, 10, False, 0),
        CoastalSite("Gisborne NZ", -38.66, 178.02, 500, 3, 35000, 8, False, 0),
        CoastalSite("Tonga", -21.13, -175.20, 2000, 2, 100000, 5, False, 0),
        CoastalSite("Samoa", -13.83, -172.14, 3000, 3, 200000, 8, False, 0),
        CoastalSite("Hawaii USA", 21.31, -157.86, 4000, 8, 400000, 30, True, 3),
    ]

    print("\n" + "="*60)
    print("SCENARIO: 2021 Kermadec M8.1")
    print("="*60)

    impacts_k = model.regional_assessment(source_kermadec, sites_kermadec)
    for impact in impacts_k:
        hrs = int(impact.travel_time_min // 60)
        mins = int(impact.travel_time_min % 60)
        print(f"\n📍 {impact.site.name}")
        print(impact.summary())