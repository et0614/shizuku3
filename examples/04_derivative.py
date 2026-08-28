# =====================================================================
# Example 04: Is the Derivative term worth it? (PI vs PID)
# =====================================================================
# Textbooks present PID as the standard, yet real HVAC systems almost
# always use PI only. This example runs the same day twice -- once with
# PI and once with PID (both Ziegler-Nichols tuned) -- and lets you
# judge the trade-off yourself:
#
#   + The D term brakes the approach to the setpoint (damping): watch
#     the morning pull-down and the undershoot below the setpoint.
#   - The D term reacts to every wiggle of the measurement. Our room
#     temperature sensor reports in 0.1 K steps, so the derivative is
#     a staircase that keeps kicking the valve. Compare the
#     "valve total travel" -- a proxy for actuator wear.
#
# Try afterwards: set CONTROL_INTERVAL = 1 (minute). The measured slope
# per interval approaches the 0.1 K resolution and the D term degrades
# into noise amplification -- one core reason practice stops at PI.
#
# Before running: start the emulator (Shizuku3.exe).
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

KU = 1.6               # ultimate gain from example 02 [1/K]
PU = 18.0              # ultimate period from example 02 [min]

SETPOINT = 26.0        # room temperature setpoint [C]
CONTROL_INTERVAL = 5   # control interval [min]
SIMULATE_HOURS = 24    # simulated period [h]

# Ziegler-Nichols rules
CONTROLLERS = {
    "PI":  {"KP": 0.45 * KU, "TI": PU / 1.2, "TD": 0.0},
    "PID": {"KP": 0.60 * KU, "TI": PU / 2.0, "TD": PU / 8.0},
}


def run_controller(emu, kp, ti, td):
    """Run one simulated day with a positional PI(D) controller."""
    emu.reset()
    emu.write("FanSpeedRatio", 1.0)
    log = {"time": [], "room": [], "valve": []}
    integral = 0.0
    prev_temp = None
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):
        room_temp = emu.read("RoomTemperature")
        error = room_temp - SETPOINT

        # Derivative on the measurement (avoids kicks on setpoint changes)
        derivative = 0.0
        if td and prev_temp is not None:
            derivative = kp * td * (room_temp - prev_temp) / CONTROL_INTERVAL
        prev_temp = room_temp

        valve = kp * error + integral + derivative
        if valve < 0.0 or 1.0 < valve:
            valve = max(0.0, min(1.0, valve))     # saturated: hold integral
        else:
            integral += kp * error * CONTROL_INTERVAL / ti

        emu.write("WaterValvePosition", valve)
        now = emu.step(minutes=CONTROL_INTERVAL, acceleration=FULL_SPEED)
        log["time"].append(now)
        log["room"].append(room_temp)
        log["valve"].append(valve)

    half = len(log["room"]) // 2
    log["stats"] = {
        "undershoot": SETPOINT - min(log["room"]),                  # morning dip [K]
        "mean_abs_error": sum(abs(t - SETPOINT) for t in log["room"][half:])
                          / (len(log["room"]) - half),              # last 12 h [K]
        "valve_travel": sum(abs(b - a) for a, b in zip(log["valve"], log["valve"][1:])),
        "energy": emu.read("IntegratedEnergy"),
        "ppd": (emu.read("IntegratedPPD") / emu.read("OccupiedTime")
                if 0 < emu.read("OccupiedTime") else float("nan")),
    }
    return log


def main():
    emu = Shizuku3Client()
    results = {}
    for name, prm in CONTROLLERS.items():
        print(f"Running {name} (KP={prm['KP']:.2f}, TI={prm['TI']:.1f} min, "
              f"TD={prm['TD']:.1f} min) ...")
        results[name] = run_controller(emu, prm["KP"], prm["TI"], prm["TD"])
    emu.close()

    print(f"\n===== PI vs PID ({SIMULATE_HOURS} h) =====")
    print(f"{'':22}{'PI':>10}{'PID':>10}")
    rows = [("Undershoot [K]", "undershoot", "{:.2f}"),
            ("Mean |error| (12 h) [K]", "mean_abs_error", "{:.2f}"),
            ("Valve total travel [-]", "valve_travel", "{:.1f}"),
            ("Energy [kWh]", "energy", "{:.1f}"),
            ("Averaged PPD [%]", "ppd", "{:.1f}")]
    for label, key, fmt in rows:
        print(f"{label:22}"
              f"{fmt.format(results['PI']['stats'][key]):>10}"
              f"{fmt.format(results['PID']['stats'][key]):>10}")

    # --- Chart -----------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6),
                                   height_ratios=[3, 2])
    for name, color in [("PI", "tab:blue"), ("PID", "tab:orange")]:
        ax1.plot(results[name]["time"], results[name]["room"],
                 color=color, label=name)
        ax2.plot(results[name]["time"], results[name]["valve"],
                 color=color, alpha=0.8, label=name)
    ax1.axhline(SETPOINT, color="gray", linestyle="--", label="Setpoint")
    ax1.set_ylabel("Temperature [C]")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.set_ylabel("Valve [-]")
    ax2.set_ylim(-0.05, 1.05)
    ax2.legend()
    ax2.grid(alpha=0.3)
    fig.suptitle("Example 04: PI vs PID (Ziegler-Nichols)")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
