# =====================================================================
# Example 05: Free optimization - the whole plant is yours
# =====================================================================
# So far you have only touched the water valve. The real plant has more:
# fan speed, the outdoor air damper (ventilation!), the heat exchanger
# bypass, the humidifier and the operation mode. They interact with
# each other -- and they are ALL yours now.
#
# Assignment: replace the block marked below with your own control
# logic and operate the plant for one day as well as you can.
# Any approach is allowed: schedules, rules, one PID, several PIDs...
#
# The score table at the end prints several indicators with different
# units. Two runs may each win on a different indicator. How you decide
# which run is "better" is left to you -- thinking about that question
# is part of the assignment.
#
# Hints:
#   - The default setting.ini starts on a summer day (Aug 5). Winter
#     (Jan 21) and mid-season (Apr 16) days are provided as comments in
#     setting.ini; some actuators only become meaningful there.
#   - Everything you can measure is read below; delete what you do not
#     use, but the plant does not mind being asked.
#
# Before running: start the emulator (Shizuku3.exe).
# =====================================================================
import matplotlib.pyplot as plt

from shizuku3client import FULL_SPEED, Shizuku3Client

CONTROL_INTERVAL = 5   # control interval [min] (we can only act this often)
SIMULATE_HOURS = 24    # simulated period [h]


def main():
    emu = Shizuku3Client()

    # Restart from the same initial state every time, so that runs
    # can be compared with each other (takes ~10 s).
    print("Resetting the emulator to the initial state...")
    start = emu.reset()
    print(f"Start: {start}")
    now = start   # current simulated time, updated by every step() below

    log = {"time": [], "room": [], "co2": []}
    steps = int(SIMULATE_HOURS * 60 / CONTROL_INTERVAL)
    for i in range(steps):

        # --- 1. Measure: everything you can know -----------------------
        # The clock is a sensor, too: "now" is a standard Python
        # datetime.datetime, so now.hour (0-23), now.minute and
        # now.weekday() (0=Mon .. 6=Sun) are all usable in your logic.
        room_temp = emu.read("RoomTemperature")            # [C]
        room_rh = emu.read("RoomRelativeHumidity")         # [%]
        room_co2 = emu.read("RoomCO2Level")                # [ppm]
        pmv = emu.read("RoomPMV")                          # [-]
        occupants = emu.read("OccupantCount")              # [persons]
        sa_temp = emu.read("SupplyAirTemperature")         # [C]
        sa_rh = emu.read("SupplyAirRelativeHumidity")      # [%]
        sa_flow = emu.read("SupplyAirFlowRate")            # [m3/h]
        oa_flow = emu.read("OutdoorAirFlowRate")           # [m3/h]
        water_temp = emu.read("WaterInletTemperature")     # [C]
        water_flow = emu.read("WaterFlowRate")             # [L/min]
        coil_load = emu.read("CoilLoad")                   # [kW]
        fan_power = emu.read("FanElectricity")             # [kW]
        outdoor_temp = emu.read("OutdoorTemperature")      # [C]
        outdoor_rh = emu.read("OutdoorRelativeHumidity")   # [%]
        humidifier_on = emu.read("HumidifierStatus")       # True/False

        # ================================================================
        # ====== WRITE YOUR OWN CONTROL LOGIC HERE =======================
        # Decide every actuator value from the measurements above.
        # The constants below are only placeholders (fixed operation).

        valve = 0.5            # water valve position          [0.0 .. 1.0]
        fan_ratio = 1.0        # fan speed ratio               [0.4 .. 1.0]
        oa_damper = 1.0        # outdoor air damper position   [0.0 .. 1.0]
        ahu_on = True          # AHU on/off                    True / False
        mode = 0               # 0 = auto (calendar), 1 = cooling, 2 = heating
        hex_bypass = False     # heat exchanger bypass         True / False
        humidifier = True      # humidifier enabled            True / False
        humid_setpoint = 40.0  # humidification setpoint       [%RH]
        humid_deadband = 10.0  # humidification deadband       [+/- %RH]

        # Example: time-scheduled operation (uncomment to try).
        # Running the plant only while it is needed saves a lot of
        # energy -- but start too late and the room is still hot at 9:00.
        # if 7 <= now.hour < 20:
        #     ahu_on = True
        # else:
        #     ahu_on = False
        #     valve = 0.0    # a closed valve also stops the pump energy

        # ====== END OF YOUR CONTROL LOGIC ===============================
        # ================================================================

        # --- 3. Actuate: send every decision to the plant ---------------
        emu.write("WaterValvePosition", valve)
        emu.write("FanSpeedRatio", fan_ratio)
        emu.write("OADamperPosition", oa_damper)
        emu.write("AHUOnOff", ahu_on)
        emu.write("OperationMode", mode)
        emu.write("HEXBypass", hex_bypass)
        emu.write("HumidifierEnabled", humidifier)
        emu.write("HumiditySetPoint", humid_setpoint)
        emu.write("HumidityDeadband", humid_deadband)

        # --- Advance time (the next chance to act is 5 minutes later) --
        now = emu.step(minutes=CONTROL_INTERVAL, acceleration=FULL_SPEED)

        log["time"].append(now)
        log["room"].append(room_temp)
        log["co2"].append(room_co2)
        print(f"{now:%H:%M}  room {room_temp:5.1f} C  CO2 {room_co2:5.0f} ppm"
              f"  valve {valve:4.2f}  fan {fan_ratio:4.2f}  OA {oa_damper:4.2f}")

    # --- Score of the day ---------------------------------------------
    print("\n===== Result of the 24 hours =====")
    print(f"Energy consumption      : {emu.read('IntegratedEnergy'):7.1f} kWh")
    occupied = emu.read("OccupiedTime")
    if 0 < occupied:
        print(f"Averaged PPD (occupied) : {emu.read('IntegratedPPD') / occupied:7.1f} %")
    print(f"CO2 excess time         : {emu.read('CO2ExcessTime'):7.2f} h")
    emu.close()

    # --- Chart ----------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6),
                                   height_ratios=[2, 2])
    ax1.plot(log["time"], log["room"], label="Room")
    ax1.set_ylabel("Temperature [C]")
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax2.plot(log["time"], log["co2"], color="tab:green", label="Room CO2")
    ax2.axhline(1000, color="tab:red", linestyle="--", linewidth=0.8,
                label="Sanitation law limit")
    ax2.set_ylabel("CO2 [ppm]")
    ax2.legend()
    ax2.grid(alpha=0.3)
    fig.suptitle("Example 05: Free optimization")
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
