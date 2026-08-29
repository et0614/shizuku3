# Gymnasium environment for the Shizuku3 building emulator.
#
# Wraps the BACnet client into the standard RL interface:
#
#   env = Shizuku3Env()
#   obs, info = env.reset()          # reinitialize the emulator (one episode = one day)
#   obs, reward, terminated, truncated, info = env.step(action)
#
# The REWARD defined here is a deliberately simple example (energy +
# comfort, with disqualification on a CO2 violation -- the same rule as
# the free-optimization assignment). Designing the reward is the heart
# of applying RL; treat this one as a starting point to criticize and
# improve, not as the answer.
import math

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from shizuku3client import FULL_SPEED, Shizuku3Client


class Shizuku3Env(gym.Env):
    """One episode = one simulated day of operating the AHU."""

    metadata = {"render_modes": []}

    # ---- example reward parameters (modify and study the consequences!)
    W_ENERGY = 1.0       # penalty per kWh consumed
    W_COMFORT = 1.0      # penalty per %h of PPD while occupied
    CO2_LIMIT = 1000.0   # ppm; exceeding this while occupied ...
    CO2_PENALTY = 100.0  # ... ends the episode with this penalty (disqualification)

    #: points read back from the emulator on every step
    _READS = ["RoomTemperature", "RoomRelativeHumidity", "RoomCO2Level",
              "OutdoorTemperature", "OccupantCount", "RoomPPD", "IntegratedEnergy"]

    def __init__(self, client=None, control_interval=5.0, episode_hours=24.0,
                 full_actions=True):
        self.emu = client if client is not None else Shizuku3Client()
        self.control_interval = control_interval
        self.max_steps = int(episode_hours * 60 / control_interval)

        # Observation: [room temp, room RH, CO2, outdoor temp, occupants,
        #               sin(hour), cos(hour)] -- all scaled to roughly 0..1
        self.observation_space = spaces.Box(-1.0, 2.0, shape=(7,), dtype=np.float32)
        # Action (all 0..1; discrete devices are threshold-encoded):
        #   [0] water valve position
        #   [1] fan speed (maps to 0.4..1.0)
        #   [2] outdoor air damper position
        # and, when full_actions=True (parity with the free assignment):
        #   [3] AHU on/off        (on if 0.5 < a)
        #   [4] operation mode    (cooling if a <= 0.5, heating otherwise)
        #   [5] HEX bypass        (bypass if 0.5 < a)
        #   [6] humidifier enable (enabled if 0.5 < a)
        self.full_actions = full_actions
        n_act = 7 if full_actions else 3
        self.action_space = spaces.Box(0.0, 1.0, shape=(n_act,), dtype=np.float32)

    # ---- helpers -----------------------------------------------------

    def _make_obs(self, rt, rh, co2, ot, occ, when):
        hour = when.hour + when.minute / 60
        return np.array([
            rt / 45.0,
            rh / 100.0,
            min(co2, 2000.0) / 2000.0,
            (ot + 5.0) / 45.0,
            occ / 30.0,
            0.5 + 0.5 * math.sin(2 * math.pi * hour / 24),
            0.5 + 0.5 * math.cos(2 * math.pi * hour / 24),
        ], dtype=np.float32)

    # ---- Gymnasium API -----------------------------------------------

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        when = self.emu.reset()
        if not self.full_actions:
            # Reduced action set: fix the remaining devices to sane defaults
            self.emu.write("AHUOnOff", True)
            self.emu.write("OperationMode", 0)
        self.steps = 0
        self.prev_energy = 0.0
        obs = self._make_obs(self.emu.read("RoomTemperature"),
                             self.emu.read("RoomRelativeHumidity"),
                             self.emu.read("RoomCO2Level"),
                             self.emu.read("OutdoorTemperature"),
                             self.emu.read("OccupantCount"), when)
        return obs, {"time": when}

    def step(self, action):
        a = np.clip(np.asarray(action, dtype=float), 0.0, 1.0)
        writes = {
            "WaterValvePosition": float(a[0]),
            "FanSpeedRatio": 0.4 + 0.6 * float(a[1]),
            "OADamperPosition": float(a[2]),
        }
        if self.full_actions:
            writes["AHUOnOff"] = 0.5 < a[3]
            writes["OperationMode"] = 2 if 0.5 < a[4] else 1
            writes["HEXBypass"] = 0.5 < a[5]
            writes["HumidifierEnabled"] = 0.5 < a[6]
        when, vals = self.emu.step_batch(minutes=self.control_interval,
                                         acceleration=FULL_SPEED,
                                         writes=writes, reads=self._READS)
        rt, rh, co2, ot, occ, ppd, energy = vals
        self.steps += 1

        # ---- example reward: negative cost of this interval ------------
        interval_h = self.control_interval / 60
        energy_used = energy - self.prev_energy
        self.prev_energy = energy
        reward = -self.W_ENERGY * energy_used
        if 0 < occ:
            reward -= self.W_COMFORT * ppd * interval_h

        terminated = False
        if 0 < occ and self.CO2_LIMIT < co2:
            # Health is a threshold, not a trade-off: disqualify the episode.
            reward -= self.CO2_PENALTY
            terminated = True

        truncated = self.max_steps <= self.steps
        obs = self._make_obs(rt, rh, co2, ot, occ, when)
        info = {"time": when, "energy": energy, "ppd": ppd, "co2": co2,
                "occupants": occ, "room_temp": rt}
        return obs, reward, terminated, truncated, info

    def close(self):
        self.emu.close()


