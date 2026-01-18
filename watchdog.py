import time
import subprocess
import os
import sys
import signal
from datetime import datetime

# Configuration
BOTS = [
    {
        "name": "Momentum Bot",
        "script": "src/bot_momentum.py",
        "log_file": "logs/momentum_events.log",
        "timeout_seconds": 300  # 5 minutes
    }
]

processes = {}

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [WATCHDOG] {message}")

def start_bot(bot_config):
    """Start a bot subprocess"""
    name = bot_config["name"]
    script = bot_config["script"]
    
    log(f"Starting {name} ({script})...")
    
    # Open logs for stdout/stderr redirection if needed, 
    # but for now we let them print to console so user sees what's happening
    # We use preexec_fn=os.setsid to allow killing the whole process group if needed
    p = subprocess.Popen(
        [sys.executable, script],
        cwd=os.getcwd(),
        # stdout=subprocess.PIPE, # Keep output in terminal for user to see
        # stderr=subprocess.PIPE
    )
    processes[name] = p
    return p

def kill_bot(name):
    """Kill a bot process"""
    if name in processes:
        p = processes[name]
        log(f"Killing {name} (PID: {p.pid})...")
        try:
            # Try gentle kill first
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if stuck
                log(f"{name} stuck, force killing...")
                p.kill()
        except Exception as e:
            log(f"Error killing {name}: {e}")
        del processes[name]

def check_staleness(bot_config):
    """Check if bot log is stale"""
    log_file = bot_config["log_file"]
    limit = bot_config["timeout_seconds"]
    
    if not os.path.exists(log_file):
        # If log doesn't exist yet, that's okay, maybe it's starting
        return False
        
    last_mod = os.path.getmtime(log_file)
    age = time.time() - last_mod
    
    if age > limit:
        log(f"⚠️ {bot_config['name']} LOG IS STALE! No updates in {int(age)}s (Limit: {limit}s)")
        return True
    
    return False

def main():
    log("Starting Watchdog... Press Ctrl+C to stop.")
    
    # Initial Start
    for bot in BOTS:
        start_bot(bot)
    
    try:
        while True:
            time.sleep(60)  # Check every minute
            
            for bot in BOTS:
                name = bot["name"]
                
                # 1. Check if process is dead
                if name in processes:
                    if processes[name].poll() is not None:
                        log(f"⚠️ {name} has CRASHED (Exit Code: {processes[name].poll()}). Restarting...")
                        del processes[name]
                        start_bot(bot)
                        continue
                else:
                    # Should be running but isn't
                    start_bot(bot)
                    continue

                # 2. Check for staleness (freeze)
                if check_staleness(bot):
                    log(f"♻️ Restarting frozen {name}...")
                    kill_bot(name)
                    start_bot(bot)
                else:
                    # Optional heartbeat debug
                    # log(f"{name} is healthy.")
                    pass
                    
    except KeyboardInterrupt:
        log("Stopping Watchdog...")
        for bot in BOTS:
            kill_bot(bot["name"])
        log("All bots stopped.")

if __name__ == "__main__":
    main()
