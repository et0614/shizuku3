# =====================================================================
# Example 02: Proportional (P) control
# =====================================================================
# Same program as example 01 -- ONLY the "2. Decide" block is changed.
# On/off control can only slam the valve fully open or closed. P control
# instead opens the valve *in proportion to the error*:
#
#   valve = KP * error        (clamped to 0..1)
#
# Run this example several times with different KP and observe:
#
#   1. Small KP (e.g. 0.5) : the room settles ABOVE the setpoint.
#      This remaining gap is the "offset" (steady-state error) --
#      a P controller needs a nonzero error to keep the valve open.
#      Check "Mean error" in the score.
#   2. Larger KP           : the offset shrinks, but...
#   3. Too large KP (~1.6+): the loop starts to oscillate (hunting).
#
# Find the "ultimate gain" KU at which a steady oscillation is sustained,
# and read the "ultimate period" PU -- the peak-to-peak period [min] of
# that oscillation -- from the chart.
#
# Where does PU come from? Hunting is a cycle of acting too late:
# the controller decides only every 5 minutes and the valve needs 90 s
# to move, so each action shows its effect about L ~= 5 min later (the
# "dead time"). With a strong gain the controller keeps cooling until it
# finally SEES it went too far -- then reverses and overshoots the other
# way. "Go too far, then notice" costs about L per leg, and one full
# swing contains about four such legs, so PU ~= 4 x L ~= 18 min here.
# (The slow room only smooths the swing into a clean wave; the period
# itself is set by the dead time. Shorten the control interval and both
# PU and the hunting threshold change -- try it.)
#
# You will use KU and PU in example 03 to tune a PI controller
# (Ziegler-Nichols ultimate sensitivity method).
#
# A real-world caution: this plant is never quiet. Weather, occupants
# and the water temperature keep disturbing the loop, and the sensor
# reports in 0.1 K steps, so some wiggle is visible even at gains well
# below KU (try KP ~= 1.1). Do not take the first visible wiggle as KU.
# In the textbook, oscillation DECAYS below KU and only sustains itself
# at KU; here, disturbances keep re-exciting a lightly damped loop.
# Look instead for the gain at which a REGULAR oscillation appears --
# constant period, constant amplitude, valve swinging in sync.
# Judging this boundary is part of real-world tuning.
#
# Before running: start the emulator (Shizuku3.exe).
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

KP = 1.6               # proportional gain [1/K]  <-- change me and re-run

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
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):

        # --- 1. Measure ------------------------------------------------
        room_temp = emu.read("RoomTemperature")

        # --- 2. Decide -------------------------------------------------
        # P control: valve opening proportional to the error.
        error = room_temp - SETPOINT          # positive = too warm
        valve = max(0.0, min(1.0, KP * error))

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
    fig.suptitle(f"Example 02: P control (KP = {KP})")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
