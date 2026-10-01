"""
Runs run_daily.bat with no window, for Task Scheduler. Windows runs .pyw files with pythonw.exe,
which opens no console, so there's no window at 21:00 to close by accident.

Everything run_daily.bat prints is appended to logs/run_daily.log, and this script exits with
the batch file's exit code, so Task Scheduler's "Last run result" still shows failures.
run_daily.bat is unchanged and still works by hand.
"""
import os, subprocess, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)

with open(os.path.join(HERE, "logs", "run_daily.log"), "a", encoding="utf-8") as log:
    log.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} run_daily.bat start =====\n")
    log.flush()
    rc = subprocess.run(["cmd.exe", "/c", os.path.join(HERE, "run_daily.bat")], cwd=HERE,
                        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW).returncode
    log.write(f"===== {datetime.now().isoformat(timespec='seconds')} exit code {rc} =====\n")

sys.exit(rc)
