# Python client library for the Shizuku3 building emulator.
#
# Hides the BACnet (bacpypes3) details behind a small synchronous API:
#
#   from shizuku3client import Shizuku3Client
#   emu = Shizuku3Client()
#   emu.write("WaterValvePosition", 0.6)
#   emu.step(minutes=5)          # advance 5 minutes and pause (Gym-style)
#   print(emu.read("RoomTemperature"))
#
# Japanese point names (e.g. "室温") are accepted as aliases.
import asyncio
import threading
import time
from datetime import datetime, timedelta

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import ObjectIdentifier

# Point table: name -> (object type, instance, writable)
_POINTS = {
    # Control inputs
    "WaterValvePosition":  ("analog-value", 101, True),
    "FanSpeedRatio":       ("analog-value", 102, True),
    "OADamperPosition":    ("analog-value", 103, True),
    "AHUOnOff":            ("binary-value", 104, True),
    "OperationMode":       ("analog-value", 105, True),  # 0=auto, 1=cooling, 2=heating
    "HEXBypass":           ("binary-value", 106, True),
    "HumidifierEnabled":   ("binary-value", 107, True),
    "HumiditySetPoint":    ("analog-value", 108, True),
    "HumidityDeadband":    ("analog-value", 109, True),
    # Measurements
    "RoomTemperature":         ("analog-value", 201, False),
    "RoomRelativeHumidity":    ("analog-value", 202, False),
    "RoomCO2Level":            ("analog-value", 203, False),
    "RoomPMV":                 ("analog-value", 204, False),
    "RoomPPD":                 ("analog-value", 205, False),
    "OccupantCount":           ("analog-value", 206, False),
    "SupplyAirTemperature":    ("analog-value", 211, False),
    "SupplyAirRelativeHumidity": ("analog-value", 212, False),
    "SupplyAirFlowRate":       ("analog-value", 213, False),
    "OutdoorAirFlowRate":      ("analog-value", 214, False),
    "WaterInletTemperature":   ("analog-value", 217, False),
    "WaterFlowRate":           ("analog-value", 218, False),
    "CoilLoad":                ("analog-value", 219, False),
    "FanElectricity":          ("analog-value", 220, False),
    "OutdoorTemperature":      ("analog-value", 221, False),
    "OutdoorRelativeHumidity": ("analog-value", 222, False),
    "HumidifierStatus":        ("binary-value", 224, False),
    # KPIs
    "IntegratedEnergy":        ("analog-value", 231, False),
    "IntegratedPPD":           ("analog-value", 232, False),
    "IntegratedOccupantWeightedPPD": ("analog-value", 233, False),
    "CO2ExcessTime":           ("analog-value", 234, False),
    "OccupiedTime":            ("analog-value", 235, False),
    # Simulation management
    "AccelerationRate":        ("analog-value", 301, True),
    "PauseAtDateTime":         ("characterstring-value", 302, True),
    "CurrentDateTime":         ("characterstring-value", 303, False),
    "Reinitialize":            ("binary-value", 304, True),
}

# Japanese aliases (kept for backward compatibility with the web GUI etc.)
_ALIASES = {
    "弁開度": "WaterValvePosition", "ファン回転数比": "FanSpeedRatio",
    "外気ダンパ開度": "OADamperPosition", "発停": "AHUOnOff", "冷暖モード": "OperationMode",
    "全熱交バイパス": "HEXBypass", "加湿有効": "HumidifierEnabled",
    "加湿設定湿度": "HumiditySetPoint", "加湿差動": "HumidityDeadband",
    "室温": "RoomTemperature", "室相対湿度": "RoomRelativeHumidity", "CO2": "RoomCO2Level",
    "PMV": "RoomPMV", "PPD": "RoomPPD", "在室人数": "OccupantCount",
    "給気温度": "SupplyAirTemperature", "給気相対湿度": "SupplyAirRelativeHumidity",
    "給気風量": "SupplyAirFlowRate", "外気導入量": "OutdoorAirFlowRate",
    "冷温水入口温度": "WaterInletTemperature", "冷温水流量": "WaterFlowRate",
    "コイル熱量": "CoilLoad", "ファン電力": "FanElectricity",
    "外気温度": "OutdoorTemperature", "外気相対湿度": "OutdoorRelativeHumidity",
    "加湿作動": "HumidifierStatus", "エネルギー積算": "IntegratedEnergy",
    "PPD積算": "IntegratedPPD", "人数重みPPD積算": "IntegratedOccupantWeightedPPD",
    "CO2超過時間": "CO2ExcessTime", "在室時間": "OccupiedTime",
    "加速度": "AccelerationRate", "一時停止時刻": "PauseAtDateTime",
    "現在時刻": "CurrentDateTime", "リセット": "Reinitialize",
}

_TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


class Shizuku3Client:
    """Synchronous client that hides the BACnet connection to the emulator."""

    def __init__(self, host="127.0.0.1", port=47809,
                 local_ip="127.0.0.1", local_port=47810, timeout=5.0):
        self._timeout = timeout
        self._device = Address(f"{host}:{port}")
        self._sim_time = None  # cached simulation time (kept in sync by step()/reset())
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        # If the local port is taken, try the next ones (bacpypes3 retries a failed
        # bind internally instead of raising, so probe availability ourselves).
        import socket as _socket
        for lp in range(local_port, local_port + 10):
            probe = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            try:
                probe.bind((local_ip, lp))
                probe.close()
            except OSError:
                probe.close()
                continue
            fut = asyncio.run_coroutine_threadsafe(
                self._setup(local_ip, lp), self._loop)
            fut.result(timeout)
            self.local_port = lp
            break
        else:
            raise RuntimeError(
                f"Local ports {local_port}-{local_port + 9} are all in use. "
                "Check for leftover client processes.")

    async def _setup(self, local_ip, local_port):
        args = SimpleArgumentParser().parse_args(
            ["--address", f"{local_ip}/32:{local_port}",
             "--instance", "3999", "--name", "Shizuku3Client"])
        self._app = Application.from_args(args)

    # ---- basic operations -------------------------------------------

    def _resolve(self, name):
        name = _ALIASES.get(name, name)
        if name not in _POINTS:
            raise KeyError(f"Unknown point name: {name}")
        return name, _POINTS[name]

    def read(self, name):
        """Read the present value of a point."""
        _, (otype, inst, _) = self._resolve(name)
        fut = asyncio.run_coroutine_threadsafe(
            self._app.read_property(self._device,
                                    ObjectIdentifier(f"{otype},{inst}"), "present-value"),
            self._loop)
        val = fut.result(self._timeout)
        if otype == "binary-value":
            return int(val) != 0
        if otype == "characterstring-value":
            return str(val)
        return float(val)

    def write(self, name, value):
        """Write a value to a point."""
        nm, (otype, inst, writable) = self._resolve(name)
        if not writable:
            raise ValueError(f"{nm} is read-only")
        if otype == "binary-value":
            value = 1 if value else 0
        elif otype == "analog-value":
            value = float(value)
        else:
            value = str(value)
        fut = asyncio.run_coroutine_threadsafe(
            self._app.write_property(self._device,
                                     ObjectIdentifier(f"{otype},{inst}"), "present-value", value),
            self._loop)
        fut.result(self._timeout)

    # ---- time management --------------------------------------------

    def current_time(self):
        """Return the current simulation time."""
        self._sim_time = datetime.strptime(self.read("CurrentDateTime"), _TIME_FORMAT)
        return self._sim_time

    def step(self, minutes=5.0, acceleration=3600, timeout=60.0):
        """Advance the simulation by the given minutes and pause (Gym-style step).

        The simulation time is cached between calls to avoid an extra BACnet
        round trip. If you change AccelerationRate or PauseAtDateTime yourself,
        call current_time() once to refresh the cache.
        """
        start = self._sim_time if self._sim_time is not None else self.current_time()
        pause_at = start + timedelta(minutes=minutes)
        self.write("PauseAtDateTime", pause_at.strftime(_TIME_FORMAT))
        self.write("AccelerationRate", acceleration)
        # Sleep through the bulk of the wall-clock wait, then poll for the pause.
        time.sleep(max(0.0, minutes * 60 / acceleration - 0.02))
        limit = time.time() + timeout
        while time.time() < limit:
            if self.read("AccelerationRate") == 0:
                self._sim_time = pause_at
                return pause_at
            time.sleep(0.02)
        raise TimeoutError("The emulator did not pause within the timeout")

    def step_batch(self, minutes=5.0, acceleration=3600, writes=None, reads=None,
                   timeout=60.0):
        """Fast variant of step(): performs the writes, advances the simulation
        and reads the requested points in a single event-loop call, so the
        cross-thread handoff cost is paid once instead of once per request.
        Intended for RL wrappers and batch experiments; teaching examples
        should prefer the explicit read()/write()/step() calls.

        Returns (new_simulation_time, [values of `reads` in order])."""
        start = self._sim_time if self._sim_time is not None else self.current_time()
        pause_at = start + timedelta(minutes=minutes)
        fut = asyncio.run_coroutine_threadsafe(
            self._step_batch_async(pause_at, minutes * 60 / acceleration,
                                   acceleration, writes or {}, reads or [], timeout),
            self._loop)
        values = fut.result(timeout + self._timeout)
        self._sim_time = pause_at
        return pause_at, values

    async def _step_batch_async(self, pause_at, wait_s, acceleration, writes, reads, timeout):
        async def wr(name, value):
            _, (otype, inst, _) = self._resolve(name)
            if otype == "binary-value":
                value = 1 if value else 0
            elif otype == "analog-value":
                value = float(value)
            else:
                value = str(value)
            await self._app.write_property(
                self._device, ObjectIdentifier(f"{otype},{inst}"), "present-value", value)

        async def rd(name):
            _, (otype, inst, _) = self._resolve(name)
            v = await self._app.read_property(
                self._device, ObjectIdentifier(f"{otype},{inst}"), "present-value")
            if otype == "binary-value":
                return int(v) != 0
            if otype == "characterstring-value":
                return str(v)
            return float(v)

        for n, v in writes.items():
            await wr(n, v)
        await wr("PauseAtDateTime", pause_at.strftime(_TIME_FORMAT))
        await wr("AccelerationRate", acceleration)
        await asyncio.sleep(max(0.0, wait_s - 0.01))
        deadline = self._loop.time() + timeout
        while self._loop.time() < deadline:
            if await rd("AccelerationRate") == 0:
                return list(await asyncio.gather(*(rd(n) for n in reads)))
            await asyncio.sleep(0.005)
        raise TimeoutError("The emulator did not pause within the timeout")

    def run(self, acceleration=600):
        """Run continuously (stop with stop() or by the pause-at time)."""
        far = self.current_time() + timedelta(days=365)
        self.write("PauseAtDateTime", far.strftime(_TIME_FORMAT))
        self.write("AccelerationRate", acceleration)
        self._sim_time = None  # time is now advancing freely

    def stop(self):
        """Pause the simulation."""
        self.write("AccelerationRate", 0)
        self._sim_time = None

    def reset(self, timeout=90.0):
        """Reload setting.ini, restart from the initial state and wait for
        completion (takes ~10 s). Returns the simulation start time."""
        self.write("Reinitialize", True)
        limit = time.time() + timeout
        while time.time() < limit:
            try:
                s = self.read("CurrentDateTime")
                if s:  # empty while reinitializing; a time string means done
                    self._sim_time = datetime.strptime(s, _TIME_FORMAT)
                    return self._sim_time
            except Exception:
                pass
            time.sleep(1)
        raise TimeoutError("Reinitialization did not complete (check the emulator)")

    def close(self):
        self._loop.call_soon_threadsafe(self._app.close)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(2)


if __name__ == "__main__":
    # Minimal self-test (start the emulator first)
    emu = Shizuku3Client()
    print("Simulation time:", emu.current_time())
    print("Room temp [C]:", emu.read("RoomTemperature"),
          "/ CO2 [ppm]:", emu.read("RoomCO2Level"))
    emu.write("WaterValvePosition", 0.6)
    t = emu.step(minutes=5)
    print("After 5 min step:", t, "/ Room temp [C]:", emu.read("RoomTemperature"))
    emu.close()
    print("OK")
