"""
monitor.py — Jarvis's nervous system: live machine vitals via psutil.

One SystemMonitor object, one .sample() call per UI refresh. It returns
everything the HUD displays:

    cpu        total CPU % and per-core list
    mem        RAM used %
    disk       home-volume used % and free GB
    battery    percent + charging flag (None on desktops)
    net        upload/download KB/s since the last sample
    top_cpu    processes eating the most CPU right now
    top_mem    processes hoarding the most memory

.warnings() turns those numbers into Sentinel-style alerts WITH
hysteresis — an alert fires once when a line is crossed and won't repeat
until the value recovers, so the HUD warns instead of nagging.
"""

import time
from collections import deque

import psutil

CPU_ALERT = 85.0      # sustained CPU above this → warning
CPU_CLEAR = 65.0      # …armed again only after dropping below this
CPU_STREAK = 3        # samples in a row before we call it "sustained"
MEM_ALERT = 85.0
DISK_ALERT = 90.0
DISK_CRIT = 95.0
BATT_ALERT = 15


class SystemMonitor:
    def __init__(self):
        self.cpu_history = deque([0.0] * 60, maxlen=60)   # for the sparkline
        self._last_net = psutil.net_io_counters()
        self._last_time = time.time()
        self._cpu_streak = 0
        self._armed = {"cpu": True, "mem": True, "disk90": True,
                       "disk95": True, "batt": True}
        psutil.cpu_percent(None)                          # prime the counter

    # ------------------------------------------------------------------ sample

    def sample(self) -> dict:
        percpu = psutil.cpu_percent(None, percpu=True)
        cpu = sum(percpu) / max(len(percpu), 1)
        self.cpu_history.append(cpu)

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(psutil.os.path.expanduser("~")))

        batt = psutil.sensors_battery()
        battery = None
        if batt is not None:
            battery = {"percent": int(batt.percent), "charging": batt.power_plugged}

        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - self._last_time, 0.001)
        up_kbs = (net.bytes_sent - self._last_net.bytes_sent) / dt / 1024
        down_kbs = (net.bytes_recv - self._last_net.bytes_recv) / dt / 1024
        self._last_net, self._last_time = net, now

        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                procs.append((
                    (info["name"] or "?")[:24],
                    info["cpu_percent"] or 0.0,
                    info["memory_info"].rss if info["memory_info"] else 0,
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "cpu": cpu,
            "percpu": percpu,
            "mem_pct": mem.percent,
            "mem_used_gb": mem.used / 1e9,
            "mem_total_gb": mem.total / 1e9,
            "disk_pct": disk.percent,
            "disk_free_gb": disk.free / 1e9,
            "battery": battery,
            "net_up_kbs": up_kbs,
            "net_down_kbs": down_kbs,
            "top_cpu": sorted(procs, key=lambda x: -x[1])[:7],
            "top_mem": sorted(procs, key=lambda x: -x[2])[:7],
        }

    # ---------------------------------------------------------------- warnings

    def warnings(self, s: dict) -> list[str]:
        """Sentinel logic: cross a line → one alert; recover → re-arm."""
        alerts = []

        # Sustained CPU pressure — and name the culprit.
        if s["cpu"] >= CPU_ALERT:
            self._cpu_streak += 1
        else:
            self._cpu_streak = 0
        if self._cpu_streak >= CPU_STREAK and self._armed["cpu"]:
            self._armed["cpu"] = False
            culprit = s["top_cpu"][0] if s["top_cpu"] else ("?", 0, 0)
            alerts.append(f"HIGH LOAD — CPU {s['cpu']:.0f}% sustained. "
                          f"Prime suspect: {culprit[0]} ({culprit[1]:.0f}%).")
        elif s["cpu"] < CPU_CLEAR:
            self._armed["cpu"] = True

        if s["mem_pct"] >= MEM_ALERT and self._armed["mem"]:
            self._armed["mem"] = False
            culprit = s["top_mem"][0] if s["top_mem"] else ("?", 0, 0)
            alerts.append(f"MEMORY PRESSURE — RAM {s['mem_pct']:.0f}%. "
                          f"Biggest occupant: {culprit[0]} "
                          f"({culprit[2] / 1e9:.1f} GB).")
        elif s["mem_pct"] < MEM_ALERT - 10:
            self._armed["mem"] = True

        for key, threshold, label in (("disk95", DISK_CRIT, "CRITICAL"),
                                      ("disk90", DISK_ALERT, "WARNING")):
            if s["disk_pct"] >= threshold and self._armed[key]:
                self._armed[key] = False
                alerts.append(f"STORAGE {label} — disk {s['disk_pct']:.0f}% "
                              f"full, {s['disk_free_gb']:.0f} GB free.")
                break

        b = s["battery"]
        if b and not b["charging"] and b["percent"] <= BATT_ALERT and self._armed["batt"]:
            self._armed["batt"] = False
            alerts.append(f"POWER LOW — battery {b['percent']}%, not charging.")
        elif b and (b["charging"] or b["percent"] > BATT_ALERT + 10):
            self._armed["batt"] = True

        return alerts
