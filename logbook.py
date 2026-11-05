"""Timestamped log to logs/<run started>.log plus a heartbeat every minute.

The heartbeat says what the run is doing right now. A Mac that sleeps freezes
the process, so when a heartbeat arrives long after the previous one, it says
so: the gap is when the laptop was asleep and nothing ran.
"""

import datetime as dt
import os
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BEAT = 60


class Logbook:
    def __init__(self, name):
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        self.path = os.path.join(ROOT, "logs", name + ".log")
        self.f = open(self.path, "a", buffering=1)
        self.lock = threading.Lock()
        self.status = "starting"
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._beat, daemon=True)

    def __call__(self, msg):
        line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
        with self.lock:
            print(line, flush=True)
            self.f.write(line + "\n")

    def set(self, status):
        """What the run is doing now; the next heartbeat repeats it."""
        self.status = status

    def start(self):
        self.t.start()
        return self

    def _beat(self):
        last = time.time()
        while not self.stop.wait(BEAT):
            now = time.time()
            gap = now - last
            if gap > BEAT * 2:
                self(f"♥ resumed after a {gap / 60:.0f} min gap: the laptop was probably asleep, nothing ran")
            self(f"♥ alive: {self.status}")
            last = now

    def close(self):
        self.stop.set()
        self.f.close()
