import subprocess
import base64
import json
import time
import requests

FRAME_PATH = "/tmp/agent_frame.jpg"

def capture_frame():
    result = subprocess.run([
        'ffmpeg', '-f', 'avfoundation',
        '-pixel_format', 'uyvy422',
        '-framerate', '30',
        '-video_size', '640x480',
        '-i', '0',
        '-vframes', '1',
        '-update', '1',
        FRAME_PATH, '-y'
    ], capture_output=True)
    return result.returncode == 0

def analyze_and_decide(base64_image):
    response = requests.post('http://localhost:11434/api/chat', json={
        "model": "llava",
        "messages": [{
            "role": "user",
            "content": """You are an autonomous drone AI agent. Analyze this scene and decide what action to take.

Respond ONLY with a JSON object like this:
{
  "observation": "what you see in one sentence",
  "threat": "none/low/medium/high",
  "action": "hover/scan/move/orbit/land",
  "direction": "left/right/forward/backward/none",
  "reason": "why you chose this action"
}""",
            "images": [base64_image]
        }],
        "stream": False
    })
    
    text = response.json()['message']['content'].strip()
    
    # Extract JSON
    start = text.find('{')
    end = text.rfind('}') + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    return None

def run_agent(cycles=5):
    print("🤖 AUTONOMOUS DRONE AGENT STARTING")
    print("Agent will observe and decide actions independently\n")
    
    for i in range(cycles):
        print(f"[CYCLE {i+1}/{cycles}]")
        
        if not capture_frame():
            print("  ❌ Frame capture failed")
            continue
        
        with open(FRAME_PATH, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode()
        
        print("  👁️ Analyzing scene...")
        decision = analyze_and_decide(image_data)
        
        if decision:
            print(f"  📍 Observation: {decision.get('observation', '?')}")
            print(f"  ⚠️  Threat level: {decision.get('threat', '?')}")
            print(f"  🎯 Action: {decision.get('action', '?')} {decision.get('direction', '')}")
            print(f"  💭 Reason: {decision.get('reason', '?')}")
        else:
            print("  ❌ Could not parse decision")
        
        print()
        time.sleep(2)
    
    print("✅ Agent session complete")

if __name__ == "__main__":
    run_agent(cycles=5)