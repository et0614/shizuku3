# =====================================================================
# Example 06: Reinforcement learning - automating the trial and error
# =====================================================================
# In example 05 you optimized the plant by hand: try something, look at
# the scores, adjust, repeat. Reinforcement learning automates exactly
# that loop. The Agent tries actions (valve / fan / OA damper), receives
# a reward, and gradually learns a control policy.
#
# The crucial design decision is the REWARD FUNCTION -- it plays the
# same role as the grading rule of the assignment: it compresses energy,
# comfort and health (different units, different natures!) into a single
# number. YOU define it, in the marked block below, and pass it to the
# environment. The given example is intentionally simplistic: train with
# it, watch what the Agent learns, then criticize and improve it.
#
# Requirements:  pip install -e "client[rl]"
#   (already installed if you set up with setup.bat / client[all])
#
# Before running: start the emulator (Shizuku3.exe). Training takes
# roughly a minute per 1000 steps; start small and grow.
# =====================================================================
import matplotlib.pyplot as plt
from stable_baselines3 import PPO

from shizuku3gym import Shizuku3Env

TRAIN_STEPS = 1000   # training budget (288 steps = 1 simulated day)


# =====================================================================
# ====== DESIGN YOUR REWARD FUNCTION HERE =============================
# The Agent maximizes THIS number -- nothing else. It will exploit any
# loophole you leave (reward hacking). data keys:
#   room_temp, room_rh, co2, outdoor_temp, occupants, ppd,
#   energy_used [kWh in this interval], interval_h [h], time
# Return (reward, terminated); terminated=True ends the episode.
def my_reward(data):
    reward = -data["energy_used"]                       # energy cost [kWh]
    if 0 < data["occupants"]:
        # ppd [%] x interval [h] = discomfort in [%h], so that the episode
        # total equals -(energy [kWh] + PPD integral [%h]) -- the same
        # quantities as the score table of examples 01-05.
        reward -= data["ppd"] * data["interval_h"]
    terminated = False
    if 0 < data["occupants"] and 1000 < data["co2"]:
        # Disqualification on a CO2 violation, as in the assignment.
        # Question: is this penalty large enough that giving up is
        # never cheaper than operating properly? Check what the Agent
        # actually learns...
        reward -= 100.0
        terminated = True
    return reward, terminated
# ====== END OF YOUR REWARD FUNCTION ==================================
# =====================================================================


def evaluate(env, model=None):
    """Run one day with the trained policy (or constant defaults) and log it."""
    obs, info = env.reset()
    log = {"time": [], "room": [], "co2": [], "reward": 0.0}
    while True:
        if model is None:
            action = [0.5, 1.0, 1.0]                      # placeholder operation
        else:
            action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        log["time"].append(info["time"])
        log["room"].append(info["room_temp"])
        log["co2"].append(info["co2"])
        log["reward"] += reward
        if terminated or truncated:
            break
    log["energy"] = info["energy"]
    log["disqualified"] = terminated
    return log


def main():
    env = Shizuku3Env(reward_function=my_reward)

    print(f"Training PPO for {TRAIN_STEPS} steps "
          f"(~{TRAIN_STEPS // env.max_steps} simulated days)...")
    model = PPO("MlpPolicy", env, n_steps=env.max_steps, verbose=1)
    model.learn(total_timesteps=TRAIN_STEPS)
    model.save("shizuku3_ppo")

    print("\nEvaluating the trained policy over one day...")
    result = evaluate(env, model)
    print(f"Episode reward : {result['reward']:8.1f}")
    print(f"Energy         : {result['energy']:8.1f} kWh")
    print(f"Disqualified   : {result['disqualified']} (CO2 violation)")
    env.close()

    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    ax1.plot(result["time"], result["room"], label="Room")
    ax1.set_ylabel("Temperature [C]")
    ax1.grid(alpha=0.3)
    ax1.legend()
    ax2.plot(result["time"], result["co2"], color="tab:green", label="Room CO2")
    ax2.axhline(1000, color="tab:red", linestyle="--", linewidth=0.8)
    ax2.set_ylabel("CO2 [ppm]")
    ax2.grid(alpha=0.3)
    fig.suptitle("Example 06: day operated by the trained agent")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
