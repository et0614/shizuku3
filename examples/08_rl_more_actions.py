# =====================================================================
# Example 08: Opening up the full toolbox - five actions
# =====================================================================
# Examples 06/07 let the agent touch only the water valve and the AHU
# on/off. Here it additionally gets the fan speed, the outdoor-air
# damper and the total-heat-exchanger bypass:
#
#   FanSpeedRatio    : fan power scales with speed^3, and the fans HEAT
#                      the airstream (about +2.6 K in total at 100 %).
#                      Running full speed all day is wasteful twice.
#   OADamperPosition : less outdoor air = less coil load, but CO2 rises.
#                      Honest physics, though: the enthalpy wheel already
#                      recovers 76 % of the outdoor-air load and OA is
#                      only 15 % of the supply flow, so in summer the
#                      energy reward for closing the damper is SMALL.
#                      If the agent leaves it open, that may simply be
#                      the correct answer - check the numbers before
#                      calling it a failure.
#   HEXBypass        : at night the outdoor air is cooler than the room;
#                      bypassing the wheel turns ventilation into free
#                      cooling (and the lower resistance even increases
#                      the OA flow). Does the agent discover night purge?
#
# What to expect: more actions = a harder exploration problem. The
# 2-action agent needed ~100 days to find daytime-only operation; give
# this one several runs (RESUME keeps the progress) and judge only
# after 500-1000 days in total. ent_coef=0.01 keeps some exploration
# noise alive so the extra actions do not freeze early at one value.
#
# Note: the example-07 model cannot be resumed here - the action vector
# has a different size, so the network shape differs. This starts fresh
# (MODEL_PATH is different for the same reason).
#
# Requirements:  pip install -e "client[rl]"
#   (already installed if you set up with setup.bat / client[all])
# Before running: start the emulator (Shizuku3.exe). Setting
# LOG_BACNET_WRITES=false in setting.ini makes training a bit faster.
# =====================================================================
import os

import matplotlib.pyplot as plt
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from shizuku3gym import Shizuku3Env

TRAIN_STEPS = 96*200    # training budget for THIS run (96 steps = 1 day @15 min)
                        # With 5 actions one run is rarely enough: keep
                        # re-running (RESUME continues from the zip) and watch
                        # the live chart until the reward stops improving.
#TRAIN_STEPS = 0        # set 0 to skip training and only EVALUATE the saved model
MODEL_PATH = "shizuku3_ppo3"
RESUME = True          # continue from MODEL_PATH.zip if it exists
                       # (delete the file or set False to start fresh;
                       #  keep control_interval/actions unchanged when resuming)
RANDOMIZE_SEEDS = False  # True: every training episode is a DIFFERENT day
                         # (same statistics: fresh weather/occupant/water
                         # seeds each reset). A fixed day can be handled by
                         # replaying the clock; different days force the
                         # policy to read its sensors. Spaces are unchanged,
                         # so an existing model can be resumed into this.
RESET_EXPLORATION = False  # True (with RESUME): widen the policy's action
                           # noise back to its initial value. After long
                           # training sigma has shrunk - the model "knows
                           # what it does" and barely tries anything new.
                           # Resetting only sigma keeps the learned mean
                           # (the schedule) but restores the appetite for
                           # experiments - the standard warm-start remedy.

# The five actions that matter in summer. OperationMode (cooling/heating)
# and HumidifierEnabled are left out on purpose: heating in August is a
# pure trap, and the humidifier only works in heating mode - useless
# action dimensions just dilute the exploration.
ACTIONS = ["WaterValvePosition", "AHUOnOff", "FanSpeedRatio",
           "OADamperPosition", "HEXBypass"]


# =====================================================================
# ====== DESIGN YOUR REWARD FUNCTION HERE =============================
# Same reward as example 07: every term stays proportional so that any
# small improvement is rewarded, and the comfort target is the same
# 26 C room setpoint as the PID examples for direct comparison.
W_TMP = 2.0    # per K of room-temperature deviation from the setpoint
W_CO2 = 0.01   # per ppm above the 1000 ppm health limit
SETPOINT = 26.0


def my_reward(data):
    reward = -data["energy_used"]                       # energy cost [kWh]
    if 0 < data["occupants"]:
        reward -= W_TMP * abs(data["room_temp"] - SETPOINT)  # comfort
        if 1000 < data["co2"]:
            reward -= W_CO2 * (data["co2"] - 1000)      # health (proportional)
    return reward, False
# ====== END OF YOUR REWARD FUNCTION ==================================
# =====================================================================


class LiveRewardPlot(BaseCallback):
    """Live chart of the reward of every finished episode (simulated day),
    so you can watch the agent improve while the training runs."""

    def _on_training_start(self):
        self.rewards = []
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(7, 4))
        self.fig.canvas.manager.set_window_title("Training progress")

    def _on_step(self):
        for done, info in zip(self.locals["dones"], self.locals["infos"]):
            if done and "episode" in info:
                self.rewards.append(info["episode"]["r"])
                self.ax.clear()
                self.ax.plot(self.rewards, marker=".")
                self.ax.set_xlabel("Episode (simulated day)")
                self.ax.set_ylabel("Episode reward")
                self.ax.grid(alpha=0.3)
                self.fig.canvas.draw_idle()
        # Service the GUI event loop on every step; otherwise Windows
        # marks the chart window as "not responding" between episodes.
        try:
            self.fig.canvas.flush_events()
        except Exception:
            pass
        return True

    def _on_training_end(self):
        plt.ioff()


def evaluate(env, model, reset_options=None):
    """Run one day with the trained policy and log it (incl. actions).
    reset_options overrides the emulator seeds/date for this evaluation
    (see Shizuku3Env.reset), e.g. {"occupant_seed": 99}."""
    obs, info = env.reset(options=reset_options)
    log = {"time": [], "room": [], "co2": [], "reward": 0.0,
           "actions": {name: [] for name in env.actions}}
    while True:
        action, _ = model.predict(obs, deterministic=True)
        a = np.clip(np.asarray(action, dtype=float), 0.0, 1.0)
        for i, name in enumerate(env.actions):
            log["actions"][name].append(float(env.ACTION_MAP[name](a[i])))
        obs, reward, terminated, truncated, info = env.step(action)
        log["time"].append(info["time"])
        log["room"].append(info["room_temp"])
        log["co2"].append(info["co2"])
        log["reward"] += reward
        if terminated or truncated:
            break
    return log


def main():
    env = Shizuku3Env(control_interval=15, actions=ACTIONS,
                      reward_function=my_reward,
                      randomize_seeds=RANDOMIZE_SEEDS)

    if RESUME and os.path.exists(MODEL_PATH + ".zip"):
        print(f"Loading the saved model {MODEL_PATH}.zip ...")
        model = PPO.load(MODEL_PATH, env=env)
        if RESET_EXPLORATION:
            import torch
            with torch.no_grad():
                print(f"Exploration reset: sigma "
                      f"{model.policy.log_std.exp().mean():.3f} -> 1.0")
                model.policy.log_std.fill_(0.0)   # log(1.0) = initial width
    else:
        print("Starting a fresh model...")
        model = PPO("MlpPolicy", env, n_steps=env.max_steps, ent_coef=0.01,
                    verbose=1)

    if 0 < TRAIN_STEPS:
        print(f"Training PPO for {TRAIN_STEPS} more steps "
              f"(~{TRAIN_STEPS // env.max_steps} simulated days)...")
        model.learn(total_timesteps=TRAIN_STEPS, callback=LiveRewardPlot(),
                    reset_num_timesteps=False)
        model.save(MODEL_PATH)
    else:
        print("TRAIN_STEPS = 0 : no training, evaluating the model as-is.")

    print("\nEvaluating the trained policy over one day...")
    # Generalization check: evaluate on "another day with the same
    # statistics" by overriding the emulator seeds. Remove reset_options
    # to evaluate on the standard day the agent was trained on.
    result = evaluate(env, model)
    emu = env.emu
    occupied = emu.read("OccupiedTime")
    print(f"Episode reward : {result['reward']:8.1f}")
    print(f"Energy         : {emu.read('IntegratedEnergy'):8.1f} kWh")
    if 0 < occupied:
        print(f"Averaged PPD   : {emu.read('IntegratedPPD') / occupied:8.1f} %")
    print(f"CO2 excess     : {emu.read('CO2ExcessTime'):8.2f} h"
          "   <- the GRADING rule still disqualifies if > 0")
    env.close()

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, sharex=True, figsize=(10, 8))
    ax1.plot(result["time"], result["room"], label="Room")
    ax1.axhline(SETPOINT, color="gray", linestyle="--", linewidth=0.8,
                label="Setpoint")
    ax1.set_ylabel("Temperature [C]")
    ax1.grid(alpha=0.3)
    ax1.legend()
    ax2.plot(result["time"], result["co2"], color="tab:green", label="Room CO2")
    ax2.axhline(1000, color="tab:red", linestyle="--", linewidth=0.8)
    ax2.set_ylabel("CO2 [ppm]")
    ax2.grid(alpha=0.3)
    for name, series in result["actions"].items():
        ax3.step(result["time"], series, where="post", label=name)
    ax3.set_ylabel("Actions")
    ax3.set_ylim(-0.05, 1.05)
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.3)
    fig.suptitle("Example 08: day operated by the 5-action agent")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
