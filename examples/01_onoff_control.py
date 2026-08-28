# =====================================================================
# Example 01: On/Off control - the simplest automatic control
# =====================================================================
# When you operated the plant from the GUI, *you* were the controller:
# you watched the room temperature and opened or closed the valve.
# This program hands that judgement over to the computer.
# The essence of automatic control is just three steps:
#
#   1. Measure  (read the room temperature)
#   2. Decide   (compare it with the setpoint)
#   3. Actuate  (open or close the valve)
#
# ...repeated at a fixed interval (here: every 5 minutes).
# Examples 02 and 03 keep exactly this structure and change ONLY the
# "2. Decide" block. Compare the three files side by side.
#
# Things to observe:
#   - Is the room temperature kept near the setpoint?
#   - How large is the temperature swing around the setpoint?
#   - How much does the valve move (see "Valve total travel")?
#     What would happen to real equipment moving this often?
#
# Before running: start the emulator (Shizuku3.exe).
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

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
        # On/off: warmer than the setpoint -> valve fully open,
        # cooler than the setpoint -> valve fully closed.
        error = room_temp - SETPOINT          # positive = too warm
        if 0 < error:
            valve = 1.0
        else:
            valve = 0.0

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
    fig.suptitle("Example 01: On/Off control")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
