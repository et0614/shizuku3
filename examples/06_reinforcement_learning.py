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
# number. The example reward lives in Shizuku3Env (client/shizuku3gym.py)
# and is intentionally simplistic. After the first training, open it,
# criticize it, and improve it. Beware of reward hacking: the Agent will
# exploit any loophole you leave.
#
# Requirements (in addition to the client):
#   pip install gymnasium stable-baselines3
#
# Before running: start the emulator (Shizuku3.exe). Training takes
# roughly a minute per 1000 steps; start small and grow.
# =====================================================================
import matplotlib.pyplot as plt
from stable_baselines3 import PPO

from shizuku3gym import Shizuku3Env

TRAIN_STEPS = 20_000   # training budget (288 steps = 1 simulated day)


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
    env = Shizuku3Env()

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
