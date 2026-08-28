# =====================================================================
# Example 02: Proportional (P) control
# =====================================================================
# On/off control (example 01) can only slam the valve fully open or
# closed. P control instead opens the valve *in proportion to the error*:
#
#   valve = KP * (room_temp - setpoint)        (clamped to 0..1)
#
# Run this example several times with different KP and observe:
#
#   1. Small KP (e.g. 0.2) : the room settles ABOVE the setpoint.
#      This remaining gap is the "offset" (steady-state error) --
#      a P controller needs a nonzero error to keep the valve open.
#   2. Larger KP           : the offset shrinks, but...
#   3. Too large KP        : the loop starts to oscillate (hunting).
#
# Find the "ultimate gain" KU at which a steady oscillation is sustained,
# and read its period PU from the chart. You will use KU and PU in
# example 03 to tune a PI controller (Ziegler-Nichols ultimate
# sensitivity method).
#
# Before running: start the emulator (Shizuku3.exe).
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

#KP = 0.5               # proportional gain [1/K]  <-- change me and re-run
KP = 1.6               # proportional gain [1/K]  <-- change me and re-run
SETPOINT = 26.0        # room temperature setpoint [C]
CONTROL_INTERVAL = 5   # control interval [min]
SIMULATE_HOURS = 24    # simulated period [h]


def main():
    emu = Shizuku3Client()
    print("Resetting the emulator to the initial state...")
    start = emu.reset()
    print(f"Start: {start}, KP = {KP}")
    emu.write("FanSpeedRatio", 1.0)

    log = {"time": [], "room": [], "valve": []}
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):
        room_temp = emu.read("RoomTemperature")

        # --- P control: output proportional to the error ---------------
        error = room_temp - SETPOINT          # positive = too warm
        valve = max(0.0, min(1.0, KP * error))
        emu.write("WaterValvePosition", valve)

        now = emu.step(minutes=CONTROL_INTERVAL, acceleration=FULL_SPEED)
        log["time"].append(now)
        log["room"].append(room_temp)
        log["valve"].append(valve)

    # --- Score and offset ----------------------------------------------
    print("\n===== Result of the 24 hours =====")
    print(f"Energy consumption : {emu.read('IntegratedEnergy'):7.1f} kWh")
    occupied = emu.read("OccupiedTime")
    if 0 < occupied:
        print(f"Averaged PPD (occ.): {emu.read('IntegratedPPD') / occupied:7.1f} %")
    tail = log["room"][len(log["room"]) // 2:]  # last 12 h (after pull-down)
    print(f"Mean error (last 12 h): {sum(tail) / len(tail) - SETPOINT:+7.2f} K"
          "   <- the offset of P control")
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
