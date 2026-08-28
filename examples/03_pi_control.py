# =====================================================================
# Example 03: PI control tuned by the ultimate sensitivity method
# =====================================================================
# P control (example 02) always leaves an offset: it needs a standing
# error to keep the valve open. The Integral term accumulates the error
# over time and takes over that duty, so the error can go to zero:
#
#   valve = KP * error + (KP / TI) * integral(error dt)
#
# Tuning (Ziegler-Nichols ultimate sensitivity method):
#   1. With example 02, raise KP until a steady oscillation is sustained.
#      Record that gain KU and the oscillation period PU [min].
#   2. Set the PI parameters below to  KP = 0.45*KU,  TI = PU/1.2.
#
# (A step-response test is impractical here: the plant is never at rest --
#  weather, occupants and water temperature keep disturbing it. The
#  ultimate sensitivity method works during normal operation.)
#
# Things to observe:
#   - The offset of P control disappears. Check "Mean error".
#   - The valve settles at whatever opening the load requires,
#     without a standing error.
#   - What happens if you make TI very small? (integral oscillation)
#
# Before running: start the emulator (Shizuku3.exe).
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

KU = 1.6               # ultimate gain measured with example 02 [1/K]
PU = 18.0              # oscillation period at KU [min]
KP = 0.45 * KU         # Ziegler-Nichols PI rule
TI = PU / 1.2          # integral time [min]

SETPOINT = 26.0        # room temperature setpoint [C]
CONTROL_INTERVAL = 5   # control interval [min]
SIMULATE_HOURS = 24    # simulated period [h]


def main():
    emu = Shizuku3Client()
    print("Resetting the emulator to the initial state...")
    start = emu.reset()
    print(f"Start: {start},  KP = {KP:.2f}, TI = {TI:.1f} min")
    emu.write("FanSpeedRatio", 1.0)

    log = {"time": [], "room": [], "valve": []}
    integral = 0.0
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):
        room_temp = emu.read("RoomTemperature")
        error = room_temp - SETPOINT          # positive = too warm

        # --- PI control ------------------------------------------------
        valve = KP * error + integral
        if valve < 0.0 or 1.0 < valve:
            # Anti-windup: the valve is saturated, so do not accumulate
            # the integral any further (it could not act anyway and would
            # only delay the recovery).
            valve = max(0.0, min(1.0, valve))
        else:
            integral += KP * error * CONTROL_INTERVAL / TI
        emu.write("WaterValvePosition", valve)

        now = emu.step(minutes=CONTROL_INTERVAL, acceleration=FULL_SPEED)
        log["time"].append(now)
        log["room"].append(room_temp)
        log["valve"].append(valve)

    # --- Score -----------------------------------------------------------
    print("\n===== Result of the 24 hours =====")
    print(f"Energy consumption : {emu.read('IntegratedEnergy'):7.1f} kWh")
    occupied = emu.read("OccupiedTime")
    if 0 < occupied:
        print(f"Averaged PPD (occ.): {emu.read('IntegratedPPD') / occupied:7.1f} %")
    tail = log["room"][len(log["room"]) // 2:]
    print(f"Mean error (last 12 h): {sum(tail) / len(tail) - SETPOINT:+7.2f} K"
          "   <- compare with example 02")
    emu.close()

    # --- Chart -----------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6),
                                   height_ratios=[3, 1])
    ax1.plot(log["time"], log["room"], label="Room")
    ax1.axhline(SETPOINT, color="gray", linestyle="--", label="Setpoint")
    ax1.set_ylabel("Temperature [C]")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.plot(log["time"], log["valve"], color="tab:red")
    ax2.set_ylabel("Valve [-]")
    ax2.set_ylim(-0.05, 1.05)
    ax2.grid(alpha=0.3)
    fig.suptitle(f"Example 03: PI control (KP = {KP:.2f}, TI = {TI:.1f} min)")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
