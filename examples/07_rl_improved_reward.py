# =====================================================================
# Example 07: Fixing the reward - learning to ventilate
# =====================================================================
# Example 06 fails, and it fails in an instructive way. Its reward ends
# the episode on a CO2 violation ("disqualified, like the assignment"):
#
#   - penalty 100    : dying early is CHEAPER than operating all day
#                      (~-280 vs ~-490). The agent learns to switch
#                      everything off and end the day at 9:00.
#                      This is reward hacking.
#   - penalty 10000  : giving up is no longer profitable, but the huge,
#                      rare, terminal signal is too sparse to learn from.
#                      Worse, the truncated episodes mean the agent
#                      NEVER experiences the afternoon. Even 20,000
#                      training steps do not escape.
#
# The fix: keep the episode running and charge a PER-STEP penalty while
# CO2 is above the limit -- clearly larger than anything that can be
# gained by not ventilating (energy + comfort cost is at most ~1.7 per
# step). Violating is then never worth it, the gradient toward "open
# the damper when people are present" is dense, and every episode
# provides a full day of experience.
#
# Note: the TRAINING reward no longer equals the GRADING rule of the
# assignment (where a violation still disqualifies you). That is fine --
# and it is normal in real RL practice: the reward is shaped to make
# learning possible; the final policy is judged by the original rule.
#
# Requirements:  pip install gymnasium stable-baselines3
# Before running: start the emulator (Shizuku3.exe).
# Training takes roughly a minute per 1000 steps.
# =====================================================================
import os

import matplotlib.pyplot as plt
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from shizuku3gym import Shizuku3Env

TRAIN_STEPS = 96*200    # training budget for THIS run (96 steps = 1 day @15 min)
                        # 200 days is enough: the reward jumps around day 100
                        # (the agent discovers daytime-only operation) and
                        # saturates by day ~150. Takes roughly half an hour.
#TRAIN_STEPS = 0        # set 0 to skip training and only EVALUATE the saved model
MODEL_PATH = "shizuku3_ppo2"
RESUME = True          # continue from MODEL_PATH.zip if it exists
                       # (delete the file or set False to start fresh;
                       #  keep control_interval/actions unchanged when resuming)


# =====================================================================
# ====== DESIGN YOUR REWARD FUNCTION HERE =============================
# Design principle: give the agent a GRADIENT to climb. A flat penalty
# ("10 whenever CO2 > 1000") tells the agent nothing about whether it is
# getting closer, and a saturating one (PPD flattens near 100 % in a hot
# room) goes silent exactly where guidance is needed. Both terms below
# stay proportional, so every small improvement is rewarded.
# The comfort target is the same 26 C room setpoint as the PID examples
# (01-04), so the learned policy can be compared with them directly.
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


def evaluate(env, model):
    """Run one day with the trained policy and log it (incl. actions)."""
    obs, info = env.reset()
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
    # The agent acts every 15 minutes and controls only the water valve
    # and the AHU on/off; the fan runs at 100 % while on, and everything
    # else is fixed to sensible defaults (see Shizuku3Env.ACTION_MAP for
    # further actions to enable).
    env = Shizuku3Env(control_interval=15,
                      actions=["WaterValvePosition", "AHUOnOff"],
                      reward_function=my_reward)

    if RESUME and os.path.exists(MODEL_PATH + ".zip"):
        print(f"Loading the saved model {MODEL_PATH}.zip ...")
        model = PPO.load(MODEL_PATH, env=env)
    else:
        print("Starting a fresh model...")
        model = PPO("MlpPolicy", env, n_steps=env.max_steps, verbose=1)

    if 0 < TRAIN_STEPS:
        print(f"Training PPO for {TRAIN_STEPS} more steps "
              f"(~{TRAIN_STEPS // env.max_steps} simulated days)...")
        model.learn(total_timesteps=TRAIN_STEPS, callback=LiveRewardPlot(),
                    reset_num_timesteps=False)
        model.save(MODEL_PATH)
    else:
        print("TRAIN_STEPS = 0 : no training, evaluating the model as-is.")

    print("\nEvaluating the trained policy over one day...")
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
    fig.suptitle("Example 07: day operated by the trained agent")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()

