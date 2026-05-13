from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import os
from dataclasses import dataclass, field
from datetime import datetime

# ── DATA STRUCTURE ────────────────────────────────────────────

@dataclass
class MissionData:
scenario: str = “”
start_time: datetime = field(default_factory=datetime.now)
end_time: datetime = field(default_factory=datetime.now)
location: str = “”
unaccounted: int = 0
located: int = 0
recovered: int = 0
deceased: int = 0
structures_assessed: int = 0
structures_critical: int = 0
hazard_zones: int = 0
survivor_candidates: list = field(default_factory=list)
decisions: list = field(default_factory=list)
failure_events: list = field(default_factory=list)
models_active: list = field(default_factory=list)
data_sources: list = field(default_factory=list)
max_altitude: float = 0.0
flight_duration_seconds: int = 0
battery_start: float = 0.0
battery_end: float = 0.0
notes: str = “”

# ── STYLES ────────────────────────────────────────────────────

def build_styles():
base = getSampleStyleSheet()

```
styles = {
    'title': ParagraphStyle(
        'BeaconTitle',
        fontSize=28,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0A0D14'),
        spaceAfter=4,
        leading=32,
    ),
    'subtitle': ParagraphStyle(
        'BeaconSubtitle',
        fontSize=13,
        fontName='Helvetica',
        textColor=colors.HexColor('#374151'),
        spaceAfter=2,
        leading=16,
    ),
    'section': ParagraphStyle(
        'BeaconSection',
        fontSize=11,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0A0D14'),
        spaceBefore=16,
        spaceAfter=6,
        leading=14,
        borderPadding=(0, 0, 4, 0),
    ),
    'body': ParagraphStyle(
        'BeaconBody',
        fontSize=9,
        fontName='Helvetica',
        textColor=colors.HexColor('#374151'),
        spaceAfter=3,
        leading=13,
    ),
    'mono': ParagraphStyle(
        'BeaconMono',
        fontSize=8,
        fontName='Courier',
        textColor=colors.HexColor('#374151'),
        spaceAfter=2,
        leading=11,
    ),
    'alert': ParagraphStyle(
        'BeaconAlert',
        fontSize=9,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#EF4444'),
        spaceAfter=3,
        leading=13,
    ),
    'good': ParagraphStyle(
        'BeaconGood',
        fontSize=9,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor('#22C55E'),
        spaceAfter=3,
        leading=13,
    ),
}
return styles
```

# ── TABLE STYLE ───────────────────────────────────────────────

def make_table_style(header=True):
style = [
(‘FONTNAME’, (0, 0), (-1, -1), ‘Helvetica’),
(‘FONTSIZE’, (0, 0), (-1, -1), 8),
(‘TEXTCOLOR’, (0, 0), (-1, -1), colors.HexColor(’#374151’)),
(‘ROWBACKGROUNDS’, (0, 1), (-1, -1), [colors.HexColor(’#F9FAFB’), colors.white]),
(‘GRID’, (0, 0), (-1, -1), 0.5, colors.HexColor(’#E5E7EB’)),
(‘TOPPADDING’, (0, 0), (-1, -1), 5),
(‘BOTTOMPADDING’, (0, 0), (-1, -1), 5),
(‘LEFTPADDING’, (0, 0), (-1, -1), 8),
(‘RIGHTPADDING’, (0, 0), (-1, -1), 8),
]
if header:
style += [
(‘BACKGROUND’, (0, 0), (-1, 0), colors.HexColor(’#0A0D14’)),
(‘TEXTCOLOR’, (0, 0), (-1, 0), colors.white),
(‘FONTNAME’, (0, 0), (-1, 0), ‘Helvetica-Bold’),
(‘FONTSIZE’, (0, 0), (-1, 0), 8),
]
return TableStyle(style)

# ── HELPERS ───────────────────────────────────────────────────

def fmt_duration(seconds):
h = seconds // 3600
m = (seconds % 3600) // 60
s = seconds % 60
return f”{h:02d}h {m:02d}m {s:02d}s”

def fmt_time(dt):
return dt.strftime(”%Y-%m-%d %H:%M:%S”)

def divider():
return HRFlowable(width=“100%”, thickness=0.5, color=colors.HexColor(’#E5E7EB’), spaceAfter=8, spaceBefore=4)

# ── GENERATOR ─────────────────────────────────────────────────

def generate_report(data: MissionData) -> str:
“””
Generate a PDF mission report from MissionData.
Returns the path to the generated PDF.
“””
os.makedirs(“reports”, exist_ok=True)
timestamp = datetime.now().strftime(”%Y%m%d_%H%M%S”)
filename = f”reports/beacon_mission_{data.scenario}_{timestamp}.pdf”

```
doc = SimpleDocTemplate(
    filename,
    pagesize=letter,
    leftMargin=0.75*inch,
    rightMargin=0.75*inch,
    topMargin=0.75*inch,
    bottomMargin=0.75*inch,
)

styles = build_styles()
content = []

# ── HEADER ──────────────────────────────────────────────
content.append(Paragraph("BEACON", styles['title']))
content.append(Paragraph("Autonomous Disaster Response System — Mission Report", styles['subtitle']))
content.append(Spacer(1, 4))
content.append(Paragraph(f"Scenario: {data.scenario.upper().replace('_', ' ')}", styles['subtitle']))
content.append(Paragraph(f"Generated: {fmt_time(datetime.now())}", styles['mono']))
content.append(divider())

# ── SECTION 1 — MISSION OVERVIEW ────────────────────────
content.append(Paragraph("1. MISSION OVERVIEW", styles['section']))

overview_data = [
    ['Field', 'Value'],
    ['Scenario', data.scenario.upper().replace('_', ' ')],
    ['Location', data.location or 'Not specified'],
    ['Start Time', fmt_time(data.start_time)],
    ['End Time', fmt_time(data.end_time)],
    ['Duration', fmt_duration(data.flight_duration_seconds)],
    ['Max Altitude', f"{data.max_altitude:.1f} m ({data.max_altitude * 3.28:.0f} ft)"],
    ['Battery Start', f"{data.battery_start:.0f}%"],
    ['Battery End', f"{data.battery_end:.0f}%"],
    ['Battery Used', f"{data.battery_start - data.battery_end:.0f}%"],
    ['Models Active', str(len(data.models_active))],
]

t = Table(overview_data, colWidths=[2.2*inch, 4.5*inch])
t.setStyle(make_table_style())
content.append(t)
content.append(Spacer(1, 8))

# ── SECTION 2 — DETECTIONS ──────────────────────────────
content.append(Paragraph("2. WHAT BEACON FOUND", styles['section']))

if data.survivor_candidates:
    content.append(Paragraph(f"Survivor Candidates Detected: {len(data.survivor_candidates)}", styles['alert']))
    cand_data = [['#', 'Latitude', 'Longitude', 'Bearing', 'Confidence', 'Temperature']]
    for i, c in enumerate(data.survivor_candidates, 1):
        cand_data.append([
            str(i),
            f"{c.get('lat', 'N/A')}",
            f"{c.get('lon', 'N/A')}",
            f"{c.get('bearing_deg', 'N/A')}°",
            f"{c.get('confidence', 0)*100:.0f}%",
            f"{c.get('temperature_c', 'N/A')}°C",
        ])
    t = Table(cand_data, colWidths=[0.35*inch, 1.1*inch, 1.1*inch, 0.8*inch, 1.0*inch, 1.2*inch])
    t.setStyle(make_table_style())
    content.append(t)
else:
    content.append(Paragraph("No survivor candidates detected.", styles['body']))

content.append(Spacer(1, 6))

hazard_data = [
    ['Metric', 'Value'],
    ['Structures Assessed', str(data.structures_assessed)],
    ['Structures Critical', str(data.structures_critical)],
    ['Hazard Zones Active', str(data.hazard_zones)],
]
t = Table(hazard_data, colWidths=[2.2*inch, 4.5*inch])
t.setStyle(make_table_style())
content.append(t)
content.append(Spacer(1, 8))

# ── SECTION 3 — PERSONNEL STATUS ────────────────────────
content.append(Paragraph("3. PERSONNEL STATUS", styles['section']))

total_missing = data.unaccounted + data.located + data.recovered + data.deceased
personnel_data = [
    ['Status', 'Count'],
    ['Reported Missing', str(total_missing)],
    ['Unaccounted', str(data.unaccounted)],
    ['Located (Thermal)', str(data.located)],
    ['Recovered', str(data.recovered)],
    ['Deceased (Confirmed)', str(data.deceased)],
]
t = Table(personnel_data, colWidths=[2.2*inch, 4.5*inch])
ts = make_table_style()
# Highlight unaccounted row in red if > 0
if data.unaccounted > 0:
    ts.add('TEXTCOLOR', (0, 2), (-1, 2), colors.HexColor('#EF4444'))
    ts.add('FONTNAME', (0, 2), (-1, 2), 'Helvetica-Bold')
t.setStyle(ts)
content.append(t)
content.append(Spacer(1, 8))

# ── SECTION 4 — DECISION LOG ────────────────────────────
content.append(Paragraph("4. DECISION LOG", styles['section']))

if data.decisions:
    dec_data = [['Time', 'Recommendation', 'Outcome']]
    for d in data.decisions:
        dec_data.append([
            d.get('time', ''),
            d.get('recommendation', ''),
            d.get('outcome', ''),
        ])
    t = Table(dec_data, colWidths=[1.0*inch, 4.5*inch, 1.2*inch])
    ts = make_table_style()
    for i, d in enumerate(data.decisions, 1):
        if d.get('outcome') == 'EXECUTED':
            ts.add('TEXTCOLOR', (2, i), (2, i), colors.HexColor('#22C55E'))
        elif d.get('outcome') == 'REJECTED':
            ts.add('TEXTCOLOR', (2, i), (2, i), colors.HexColor('#EF4444'))
    t.setStyle(ts)
    content.append(t)
else:
    content.append(Paragraph("No AI advisor decisions logged.", styles['body']))

content.append(Spacer(1, 8))

# ── SECTION 5 — FLIGHT DATA ─────────────────────────────
content.append(Paragraph("5. FLIGHT DATA", styles['section']))

if data.failure_events:
    content.append(Paragraph("Failure Prediction Events:", styles['alert']))
    for event in data.failure_events:
        content.append(Paragraph(f"• {event}", styles['mono']))
else:
    content.append(Paragraph("No failure prediction events recorded.", styles['good']))

content.append(Spacer(1, 6))

if data.models_active:
    content.append(Paragraph("Active Predictive Models:", styles['body']))
    model_text = " · ".join(data.models_active)
    content.append(Paragraph(model_text, styles['mono']))

content.append(Spacer(1, 8))

# ── SECTION 6 — DATA SOURCES ────────────────────────────
content.append(Paragraph("6. DATA SOURCES", styles['section']))

if data.data_sources:
    src_data = [['Source', 'Status']]
    for src in data.data_sources:
        src_data.append([src, 'ACTIVE'])
    t = Table(src_data, colWidths=[4.0*inch, 2.7*inch])
    t.setStyle(make_table_style())
    content.append(t)
else:
    content.append(Paragraph("No data sources logged.", styles['body']))

content.append(Spacer(1, 8))

# ── NOTES ───────────────────────────────────────────────
if data.notes:
    content.append(Paragraph("7. NOTES", styles['section']))
    content.append(Paragraph(data.notes, styles['body']))
    content.append(Spacer(1, 8))

# ── FOOTER LINE ─────────────────────────────────────────
content.append(divider())
content.append(Paragraph(
    f"BEACON Autonomous Disaster Response System · Report generated {fmt_time(datetime.now())} · CONFIDENTIAL",
    styles['mono']
))

# ── BUILD ───────────────────────────────────────────────
doc.build(content)
print(f"[REPORT] Mission report saved: {filename}")
return filename
```

# ── DEMO ──────────────────────────────────────────────────────

if **name** == “**main**”:
# Build a realistic demo mission
from datetime import timedelta

```
start = datetime(2026, 5, 11, 14, 30, 0)
end = start + timedelta(hours=1, minutes=47, seconds=23)

demo = MissionData(
    scenario="wildfire",
    start_time=start,
    end_time=end,
    location="Allen, TX — Sector 4 North Grid",
    unaccounted=14,
    located=3,
    recovered=2,
    deceased=0,
    structures_assessed=23,
    structures_critical=7,
    hazard_zones=4,
    flight_duration_seconds=int((end - start).total_seconds()),
    max_altitude=45.0,
    battery_start=100.0,
    battery_end=23.0,
    survivor_candidates=[
        {'lat': 33.1584, 'lon': -96.6735, 'bearing_deg': 47, 'confidence': 0.91, 'temperature_c': 38.2},
        {'lat': 33.1612, 'lon': -96.6698, 'bearing_deg': 112, 'confidence': 0.76, 'temperature_c': 37.8},
        {'lat': 33.1557, 'lon': -96.6751, 'bearing_deg': 223, 'confidence': 0.68, 'temperature_c': 37.1},
    ],
    decisions=[
        {'time': '14:35:22', 'recommendation': 'Deploy Drone-1 to Sector 4 North — thermal candidate at bearing 047°', 'outcome': 'EXECUTED'},
        {'time': '14:52:11', 'recommendation': 'Expand search radius to 500m — Mattson Zone 2 probability 61%', 'outcome': 'EXECUTED'},
        {'time': '15:18:44', 'recommendation': 'Return to home — battery at 30%, estimated 4min remaining', 'outcome': 'REJECTED'},
        {'time': '15:31:02', 'recommendation': 'Initiate return to home — battery at 23%', 'outcome': 'EXECUTED'},
    ],
    failure_events=[
        "15:18:44 — CAUTION: Battery 30.0%, estimated 4.2min remaining",
        "15:28:01 — WARNING: Vibration magnitude 18.4 m/s²",
    ],
    models_active=[
        'Rothermel', 'FARSITE', 'WindNinja', 'NOAA Weather',
        'Mattson SAR', 'ShakeMap', 'HAZUS', 'TRIGRS',
        'MOST', 'ALOHA', 'PAGER', 'Aftershock',
        'Foreshock', 'SLOSH', 'HEC-RAS', 'USGS Live',
    ],
    data_sources=[
        'NOAA Weather API — api.weather.gov',
        'USGS Earthquake Feed — earthquake.usgs.gov',
        'NASA FIRMS Fire Detection — firms.modaps.eosdis.nasa.gov',
        'USGS Water Services — waterservices.usgs.gov',
        'NOAA NHC Hurricane Feed',
        'DART Buoy Network — ndbc.noaa.gov',
    ],
    notes="Wind shift at 15:22 caused FARSITE model to update fire spread prediction. "
          "Ground teams notified of revised evacuation corridor. "
          "Two survivors extracted by Team Alpha at 15:45."
)

path = generate_report(demo)
print(f"Demo report generated: {path}")
```