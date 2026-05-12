from collections import deque
from pymavlink import mavutil
import time
import random
# Thresholds
BATTERY_WARNING  = 35
BATTERY_CAUTION  = 25
BATTERY_CRITICAL = 10
BATTERY_EMERGENCY = 5

VIBRATION_WARNING  = 18
VIBRATION_CAUTION  = 30
VIBRATION_CRITICAL = 60

GPS_WARNING  = 8
GPS_CAUTION  = 6
GPS_CRITICAL = 4

ATTITUDE_WARNING  = 25
ATTITUDE_CAUTION  = 35
ATTITUDE_CRITICAL = 45
status_map = {0: "OK", 1: "WARNING", 2: "CAUTION", 3: "CRITICAL", 4: "EMERGENCY"}
WINDOW             = 60
PREDICTION_INTERVAL = 5

#deques for storing recent sensor data
battery_pct     = deque(maxlen=WINDOW)
battery_current = deque(maxlen=WINDOW)
vibration_x     = deque(maxlen=WINDOW)
vibration_y     = deque(maxlen=WINDOW)
vibration_z     = deque(maxlen=WINDOW)
gps_sats        = deque(maxlen=WINDOW)
gps_fix         = deque(maxlen=WINDOW)
attitude_roll   = deque(maxlen=WINDOW)
attitude_pitch  = deque(maxlen=WINDOW)

def connect_mavlink():
    print("Connecting to SITL...")
    connection = mavutil.mavlink_connection('udp:127.0.0.1:14550')
    connection.wait_heartbeat()
    print("Heartbeat received — connected to SITL")
    return connection

def read_mavlink(connection):
    msg = connection.recv_match(
        type=['SYS_STATUS','VIBRATION','GPS_RAW_INT','ATTITUDE'],
        blocking=False
    )
    if msg is None:
        return
    t = msg.get_type()
    if t == 'SYS_STATUS':
        battery_pct.append(msg.battery_remaining)
        battery_current.append(msg.current_battery / 100.0)
    elif t == 'VIBRATION':
        vibration_x.append(msg.vibration_x)
        vibration_y.append(msg.vibration_y)
        vibration_z.append(msg.vibration_z)
    elif t == 'GPS_RAW_INT':
        gps_sats.append(msg.satellites_visible)
        gps_fix.append(msg.fix_type)
    elif t == 'ATTITUDE':
        attitude_roll.append(abs(msg.roll) * 57.3)
        attitude_pitch.append(abs(msg.pitch) * 57.3)

def trend(data, lookback=10):
    # Analyze trends in sensor data
    if len(data) < lookback:
        return 0.0
    recent = list(data)[-lookback:]
    first_half = recent[:lookback//2]
    second_half = recent[lookback//2:]
    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)
    return (avg_second - avg_first) / lookback / 2

def analyze_battery():
    if(not battery_pct):
        return 0, "insufficient data"
    pct = battery_pct[-1]
    trend_pct = trend(battery_pct)
    est_time = 0
    if(not trend_pct):
        est_time = 999
    else:
        est_time = (pct / abs(trend_pct)) / 60
    if pct <= BATTERY_EMERGENCY:
        return 4, f"EMERGENCY: {pct:.1f}% remaining, estimated {est_time:.1f} minutes left"
    elif pct <= BATTERY_CRITICAL or est_time < 2:
        return 3, f"CRITICAL: {pct:.1f}% remaining, estimated {est_time:.1f} minutes left"
    elif pct <= BATTERY_CAUTION or est_time < 5:
        return 2, f"CAUTION: {pct:.1f}% remaining, estimated {est_time:.1f} minutes left"
    elif pct <= BATTERY_WARNING:
        return 1, f"WARNING: {pct:.1f}% remaining, estimated {est_time:.1f} minutes left"
    else:
        return 0, f"{pct:.1f}% battery remaining"
def analyze_vibration():
    if(not vibration_x):
        return 0, "insufficient data"
    vib_x = vibration_x[-1]
    vib_y = vibration_y[-1]
    vib_z = vibration_z[-1]
    vib_trend = max(trend(vibration_x), trend(vibration_y), trend(vibration_z))
    vib_mag = (vib_x**2 + vib_y**2 + vib_z**2)**0.5
    if vib_mag >= VIBRATION_CRITICAL:
        return 3, f" Vibration magnitude {vib_mag:.1f} m/s²"
    elif vib_mag >= VIBRATION_CAUTION or vib_trend > 1.0:
        return 2, f" Vibration magnitude {vib_mag:.1f} m/s²"
    elif vib_mag >= VIBRATION_WARNING:
        return 1, f" Vibration magnitude {vib_mag:.1f} m/s²"
    else:
        return 0, f"Vibration magnitude {vib_mag:.1f} m/s²"

def analyze_gps():
    if(not gps_sats):
        return 0, "insufficient data"
    sats = gps_sats[-1]
    fix = gps_fix[-1]
    if sats <= GPS_CRITICAL or fix < 2:
        return 3, f"CRITICAL: {sats} satellites, fix type {fix}"
    elif sats <= GPS_CAUTION or fix < 3:
        return 2, f"CAUTION: {sats} satellites, fix type {fix}"
    elif sats <= GPS_WARNING:
        return 1, f"WARNING: {sats} satellites, fix type {fix}"
    else:
        return 0, f"{sats} satellites, fix type {fix}"
    
def analyze_attitude():
    if(not attitude_roll):
        return 0, "insufficient data"
    roll = attitude_roll[-1]
    pitch = attitude_pitch[-1]
    roll_trend = trend(attitude_roll)
    pitch_trend = trend(attitude_pitch)
    if abs(roll) >= ATTITUDE_CRITICAL or abs(pitch) >= ATTITUDE_CRITICAL:
        return 3, f"CRITICAL: Roll {roll:.1f}°, Pitch {pitch:.1f}°"
    elif abs(roll) >= ATTITUDE_CAUTION or abs(pitch) >= ATTITUDE_CAUTION or abs(roll_trend) > 2.0 or abs(pitch_trend) > 2.0:
        return 2, f"CAUTION: Roll {roll:.1f}°, Pitch {pitch:.1f}°"
    elif abs(roll) >= ATTITUDE_WARNING or abs(pitch) >= ATTITUDE_WARNING:
        return 1, f"WARNING: Roll {roll:.1f}°, Pitch {pitch:.1f}°"
    else:
        return 0, f"Roll {roll:.1f}°, Pitch {pitch:.1f}°"
    
def run_prediction():
    battery_status = analyze_battery()
    vibration_status = analyze_vibration()
    gps_status = analyze_gps()
    attitude_status = analyze_attitude()
    
    overall_status = max(battery_status[0], vibration_status[0], gps_status[0], attitude_status[0])
    
    messages = []
    for level, msg in [battery_status, vibration_status, gps_status, attitude_status]:
        if level > 0:
            messages.append(msg)

    combined = '\n'.join(messages) if messages else "All systems nominal"
    return overall_status, combined   

def handle_output(level, message):
    ts = time.strftime('%H:%M:%S')
    if level == 0:
        pass
    elif level == 1:
        print(f"[{ts}] ⚠️  WARNING: {message}")
    elif level == 2:
        print(f"[{ts}] 🟠 CAUTION: {message}")
    elif level == 3:
        print(f"[{ts}] 🔴 CRITICAL: {message}")
        print(f"[{ts}] → INITIATING RETURN TO HOME")
    elif level == 4:
        print(f"[{ts}] 🚨 EMERGENCY: {message}")
        print(f"[{ts}] → LANDING NOW")

counter = 0
if __name__ == "__main__":
    print("BEACON Failure Prediction — Running")
    conn = connect_mavlink()
    counter = 0
    while True:
        read_mavlink(conn)
        counter += 1
        if counter % PREDICTION_INTERVAL == 0:
            level, msg = run_prediction()
            handle_output(level, msg)
        time.sleep(0.1)
        if counter >= 2000:
            print("Complete.")
            break    