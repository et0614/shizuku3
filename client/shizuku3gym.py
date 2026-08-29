# Gymnasium environment for the Shizuku3 building emulator.
#
# Wraps the BACnet client into the standard RL interface:
#
#   env = Shizuku3Env(control_interval=15,
#                     actions=["WaterValvePosition", "FanSpeedRatio"],
#                     reward_function=my_reward)
#   obs, info = env.reset()          # reinitialize the emulator (one episode = one day)
#   obs, reward, terminated, truncated, info = env.step(action)
#
# Both the ACTIONS and the REWARD are chosen by the caller: picking which
# actuators the agent may touch, and designing the reward, are part of
# the exercise. Actuators that are not chosen as actions are fixed to
# sensible defaults (AHU on, mode by calendar, OA damper fully open so
# that minimum ventilation is guaranteed, HEX bypass off, humidifier on).
import math

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from shizuku3client import FULL_SPEED, Shizuku3Client


class Shizuku3Env(gym.Env):
    """One episode = one simulated day of operating the AHU."""

    metadata = {"render_modes": []}

    #: available actions: name -> function mapping the agent output [0..1]
    #: to the written value (discrete devices are threshold-encoded)
    ACTION_MAP = {
        "WaterValvePosition": lambda a: float(a),
        "FanSpeedRatio":      lambda a: 0.4 + 0.6 * float(a),  # inverter range
        "OADamperPosition":   lambda a: float(a),
        "AHUOnOff":           lambda a: 0.5 < a,
        "OperationMode":      lambda a: 2 if 0.5 < a else 1,   # cooling / heating
        "HEXBypass":          lambda a: 0.5 < a,
        "HumidifierEnabled":  lambda a: 0.5 < a,
    }

    #: defaults written on reset for every actuator (actions overwrite
    #: their own actuator on each step)
    _DEFAULTS = {"AHUOnOff": True, "OperationMode": 0, "FanSpeedRatio": 1.0,
                 "OADamperPosition": 1.0, "HEXBypass": False,
                 "HumidifierEnabled": True}

    # ---- example reward parameters (see default_reward)
    W_ENERGY = 1.0       # penalty per kWh consumed
    W_COMFORT = 1.0      # penalty per %h of PPD while occupied
    CO2_LIMIT = 1000.0   # ppm
    CO2_PENALTY = 100.0

    #: points read back from the emulator on every step
    _READS = ["RoomTemperature", "RoomRelativeHumidity", "RoomCO2Level",
              "OutdoorTemperature", "OccupantCount", "RoomPPD", "RoomPMV",
              "IntegratedEnergy"]

    def __init__(self, client=None, control_interval=5.0, episode_hours=24.0,
                 actions=None, reward_function=None):
        self.emu = client if client is not None else Shizuku3Client()
        # reward_function(data) -> (reward, terminated). See default_reward
        # for the expected signature.
        self.reward_function = reward_function or Shizuku3Env.default_reward
        self.control_interval = control_interval
        self.max_steps = int(episode_hours * 60 / control_interval)

        # Which actuators the agent controls (order = action vector order)
        self.actions = list(actions) if actions is not None else \
            ["WaterValvePosition", "FanSpeedRatio"]
        for name in self.actions:
            if name not in self.ACTION_MAP:
                raise KeyError(f"Unknown action: {name} "
                               f"(available: {list(self.ACTION_MAP)})")

        # Observation: [room temp, room RH, CO2, outdoor temp, occupants,
        #               sin(hour), cos(hour)] -- all scaled to roughly 0..1
        self.observation_space = spaces.Box(-1.0, 2.0, shape=(7,), dtype=np.float32)
        self.action_space = spaces.Box(0.0, 1.0, shape=(len(self.actions),),
                                       dtype=np.float32)

    @staticmethod
    def default_reward(data):
        """Example reward: negative cost of the interval. data keys:
        room_temp, room_rh, co2, outdoor_temp, occupants, ppd, pmv,
        energy_used [kWh in this interval], interval_h [h], time.
        Returns (reward, terminated). Designing this function is the
        heart of the exercise -- supply your own via reward_function=."""
        reward = -Shizuku3Env.W_ENERGY * data["energy_used"]
        if 0 < data["occupants"]:
            reward -= Shizuku3Env.W_COMFORT * data["ppd"] * data["interval_h"]
        terminated = False
        if 0 < data["occupants"] and Shizuku3Env.CO2_LIMIT < data["co2"]:
            reward -= Shizuku3Env.CO2_PENALTY
            terminated = True
        return reward, terminated

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
        for name, value in self._DEFAULTS.items():
            self.emu.write(name, value)
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
        writes = {name: self.ACTION_MAP[name](a[i])
                  for i, name in enumerate(self.actions)}
        when, vals = self.emu.step_batch(minutes=self.control_interval,
                                         acceleration=FULL_SPEED,
                                         writes=writes, reads=self._READS)
        rt, rh, co2, ot, occ, ppd, pmv, energy = vals
        self.steps += 1

        energy_used = energy - self.prev_energy
        self.prev_energy = energy
        data = {"room_temp": rt, "room_rh": rh, "co2": co2, "outdoor_temp": ot,
                "occupants": occ, "ppd": ppd, "pmv": pmv, "energy_used": energy_used,
                "interval_h": self.control_interval / 60, "time": when}
        reward, terminated = self.reward_function(data)

        truncated = self.max_steps <= self.steps
        obs = self._make_obs(rt, rh, co2, ot, occ, when)
        info = {"time": when, "energy": energy, "ppd": ppd, "co2": co2,
                "occupants": occ, "room_temp": rt}
        return obs, reward, terminated, truncated, info

    def close(self):
        self.emu.close()
