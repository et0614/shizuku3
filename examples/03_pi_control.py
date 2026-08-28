# =====================================================================
# Example 03: PI control tuned by the ultimate sensitivity method
# =====================================================================
# Same program as examples 01 and 02 -- ONLY the "2. Decide" block is
# changed (plus one state variable, "integral", before the loop).
#
# P control (example 02) always leaves an offset: it needs a standing
# error to keep the valve open. The Integral term accumulates the error
# over time and takes over that duty, so the error can go to zero:
#
#   valve = KP * error + integral
#
# Tuning (Ziegler-Nichols ultimate sensitivity method):
#   1. With example 02, raise KP until a steady oscillation is sustained.
#      Record that gain KU and the oscillation period PU [min].
#   2. Set KU and PU below; KP and TI follow from  KP = 0.45*KU,
#      TI = PU/1.2.
#
# (A step-response test is impractical here: the plant is never at rest --
#  weather, occupants and water temperature keep disturbing it. The
#  ultimate sensitivity method works during normal operation.)
#
# KU and PU are rough field measurements, and Ziegler-Nichols is a
# ballpark rule, not an exact law. If you judged KU differently
# (e.g. 1.2 instead of 1.6), the resulting PI is still workable --
# try both and compare the scores.
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
CONTROL_INTERVAL = 5   # control interval [min] (we can only act this often)
SIMULATE_HOURS = 24    # simulated period [h]


def main():
    emu = Shizuku3Client()

    # Restart from the same initial state every time, so that runs
    # can be compared with each other (takes ~10 s).
    print("Resetting the emulator to the initial state...")
    start = emu.reset()
    print(f"Start: {start}")

    # Run the fan at full speed; in these examples we only control the valve.
    emu.write("FanSpeedRatio", 1.0)

    log = {"time": [], "room": [], "valve": []}
    integral = 0.0
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):

        # --- 1. Measure ------------------------------------------------
        room_temp = emu.read("RoomTemperature")

        # --- 2. Decide -------------------------------------------------
        # PI control: proportional + accumulated (integral) action.
        error = room_temp - SETPOINT          # positive = too warm
        valve = KP * error + integral
        if valve < 0.0 or 1.0 < valve:
            # Anti-windup: the valve is saturated, so do not accumulate
            # the integral any further (it could not act anyway and would
            # only delay the recovery).
            valve = max(0.0, min(1.0, valve))
        else:
            integral += KP * error * CONTROL_INTERVAL / TI

        # --- 3. Actuate ------------------------------------------------
        emu.write("WaterValvePosition", valve)

        # --- Advance time (the next chance to act is 5 minutes later) --
        now = emu.step(minutes=CONTROL_INTERVAL, acceleration=FULL_SPEED)

        log["time"].append(now)
        log["room"].append(room_temp)
        log["valve"].append(valve)
        print(f"{now:%H:%M}  room {room_temp:5.1f} C  valve {valve:4.2f}")

    # --- Score of the day ---------------------------------------------
    print("\n===== Result of the 24 hours =====")
    print(f"Energy consumption    : {emu.read('IntegratedEnergy'):7.1f} kWh")
    occupied = emu.read("OccupiedTime")
    if 0 < occupied:
        print(f"Averaged PPD (occ.)   : {emu.read('IntegratedPPD') / occupied:7.1f} %")
    print(f"CO2 excess time       : {emu.read('CO2ExcessTime'):7.2f} h")
    tail = log["room"][len(log["room"]) // 2:]
    print(f"Mean error (last 12 h): {sum(tail) / len(tail) - SETPOINT:+7.2f} K")
    travel = sum(abs(b - a) for a, b in zip(log["valve"], log["valve"][1:]))
    print(f"Valve total travel    : {travel:7.1f} (full strokes)")
    emu.close()

    # --- Chart ----------------------------------------------------------
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
