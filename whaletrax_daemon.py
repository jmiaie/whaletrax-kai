#!/usr/bin/env python3
"""
WhaleTrax Watcher Daemon
Runs whaletrax_watcher.py every 15 minutes with token fix.
"""
import subprocess, time, sys, os
from pathlib import Path

TOKEN = "8678199814:AAECmOod8cH3GqKqgKnc7NdcmR1bAif2BBg"
INTERVAL = 15 * 60  # 15 minutes
WD = Path("/home/ubuntu/.openclaw/workspace/repos/whaletrax")
LOG = Path("/tmp/whaletrax_watcher.log")
PIDFILE = Path("/tmp/whaletrax_daemon.pid")

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def get_pid():
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except:
            PIDFILE.unlink(missing_ok=True)
    return None

def run_watcher():
    env = os.environ.copy()
    env["WHALETRAX_BOT_TOKEN"] = TOKEN
    result = subprocess.run(
        [sys.executable, "whaletrax_watcher.py"],
        cwd=str(WD),
        env=env,
        capture_output=True,
        text=True,
        timeout=120
    )
    return result

if __name__ == "__main__":
    # Check already running
    existing = get_pid()
    if existing:
        log(f"Daemon already running PID {existing}")
        sys.exit(0)

    # Write PID
    PIDFILE.write_text(str(os.getpid()))
    log("WhaleTrax daemon starting")
    log(f"Token: @oc_a7bot | Interval: {INTERVAL}s | Dir: {WD}")

    while True:
        run_start = time.time()
        try:
            result = run_watcher()
            for line in result.stdout.splitlines()[-5:]:
                if line.strip():
                    log(f"  [run] {line.strip()}")
            if result.returncode == 0:
                log("Run completed OK")
            else:
                log(f"Run exit code: {result.returncode}")
        except Exception as e:
            log(f"Run error: {e}")

        elapsed = time.time() - run_start
        sleep_time = max(INTERVAL - elapsed, 60)
        log(f"Sleeping {sleep_time:.0f}s until next run")
        time.sleep(sleep_time)
