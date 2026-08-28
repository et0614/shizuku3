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
#
# Before running:
#   - Start the emulator (Shizuku3.exe)
#   - pip install matplotlib  (for the result chart)
#   - The default setting.ini starts on a summer day (Aug 5) -> cooling
#
# Things to observe:
#   - Is the room temperature kept near the setpoint?
#   - How many times does the valve switch on and off?
#     What would happen to real equipment cycling this often?
#   - How large is the temperature swing around the setpoint?
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

SETPOINT = 26.0        # room temperature setpoint [C]
CONTROL_INTERVAL = 5   # control interval [min] (we can only act this often)
SIMULATE_HOURS = 24    # simulated period [h]
ACCELERATION = FULL_SPEED  # no real-time pacing: we only look at the final chart


def main():
    emu = Shizuku3Client()

    # Restart from the same initial state every time, so that runs
    # can be compared with each other (takes ~10 s).
    print("Resetting the emulator to the initial state...")
    start = emu.reset()
    print(f"Start: {start}")

    # Run the fan at full speed; in this example we only control the valve.
    emu.write("FanSpeedRatio", 1.0)

    log = {"time": [], "room": [], "outdoor": [], "valve": []}
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):

        # --- 1. Measure ------------------------------------------------
        room_temp = emu.read("RoomTemperature")

        # --- 2. Decide -------------------------------------------------
        # Warmer than the setpoint -> cool (valve fully open),
        # cooler than the setpoint -> stop (valve fully closed).
        if SETPOINT < room_temp:
            valve = 1.0   # On
        else:
            valve = 0.0   # Off

        # --- 3. Actuate ------------------------------------------------
        emu.write("WaterValvePosition", valve)

        # --- Advance time (the next chance to act is 5 minutes later) --
        now = emu.step(minutes=CONTROL_INTERVAL, acceleration=ACCELERATION)

        log["time"].append(now)
        log["room"].append(room_temp)
        log["outdoor"].append(emu.read("OutdoorTemperature"))
        log["valve"].append(valve)
        print(f"{now:%H:%M}  room {room_temp:5.1f} C  valve {'On ' if valve else 'Off'}"
              f"  (setpoint {SETPOINT} C)")

    # --- Score of the day ---------------------------------------------
    print("\n===== Result of the 24 hours =====")
    print(f"Energy consumption   : {emu.read('IntegratedEnergy'):7.1f} kWh")
    occupied = emu.read("OccupiedTime")
    if 0 < occupied:
        print(f"Averaged PPD (occ.)  : {emu.read('IntegratedPPD') / occupied:7.1f} %")
    print(f"CO2 excess time      : {emu.read('CO2ExcessTime'):7.2f} h")
    switches = sum(1 for a, b in zip(log["valve"], log["valve"][1:]) if a != b)
    print(f"Valve on/off switches: {switches:7d} times")
    emu.close()

    # --- Chart ----------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6),
                                   height_ratios=[3, 1])
    ax1.plot(log["time"], log["room"], label="Room")
    ax1.plot(log["time"], log["outdoor"], label="Outdoor", alpha=0.7)
    ax1.axhline(SETPOINT, color="gray", linestyle="--", label="Setpoint")
    ax1.set_ylabel("Temperature [C]")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.step(log["time"], log["valve"], where="post", color="tab:red")
    ax2.set_ylabel("Valve")
    ax2.set_yticks([0, 1], ["Off", "On"])
    ax2.grid(alpha=0.3)
    fig.suptitle("Example 01: On/Off control")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
