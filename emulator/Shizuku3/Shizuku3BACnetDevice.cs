using System.Globalization;
using System.IO.BACnet;
using System.IO.BACnet.Storage;
using BaCSharp;

namespace Shizuku3
{
  /// <summary>Shizuku3のBACnetデバイス（docs「03_BACnetポイント一覧.md」のポイントを公開する）</summary>
  /// <remarks>
  /// PoEMServerのBACnetCommunicator（BACnet 4.0.0 + DeviceStorage）を流用。
  /// v1の簡略化: 操作量はAnalog/Binary Value（priority arrayなし）、日時はCharacterString Value
  /// （"yyyy/MM/dd HH:mm:ss"）、リセットはBinary Value 304への書込み（ReinitializeDeviceサービスは将来対応）。
  /// 外部からの書込みはDeviceStorageのChangeOfValueイベントで検出してエミュレータに反映し、
  /// 計測値は周期タイマでエミュレータからStorageへ同期する。
  /// </remarks>
  public class Shizuku3BACnetDevice
  {

    /// <summary>書込可能ポイントの名称（操作ログ用）</summary>
    private static readonly Dictionary<uint, string> writableNames = new Dictionary<uint, string>
    {
      { 101, "WaterValvePosition" }, { 102, "FanSpeedRatio" }, { 103, "OADamperPosition" },
      { 104, "AHUOnOff" }, { 105, "OperationMode" }, { 106, "HEXBypass" },
      { 107, "HumidifierEnabled" }, { 108, "HumiditySetPoint" }, { 109, "HumidityDeadband" },
      { 301, "AccelerationRate" }, { 302, "PauseAtDateTime" }, { 304, "Reinitialize" },
    };

    private readonly BACnetCommunicator comm;
    private readonly EmulatorService svc;
    private readonly System.Timers.Timer syncTimer;
    private bool applying = false; //同期書込みとの区別用

    public Shizuku3BACnetDevice(EmulatorService service)
    {
      svc = service;
      Settings s = Settings.Instance;
      DeviceStorage storage = DeviceStorage.Load(Path.Combine(AppContext.BaseDirectory, "DeviceStorage.xml"));
      storage.DeviceId = s.DeviceID;
      comm = new BACnetCommunicator(storage, s.UdpPort, s.LocalEndpoint);

      //操作量（書込可）
      addAnalog(101, "WaterValvePosition", "Chilled/hot water valve position [0-1]", 0, 98, true);
      addAnalog(102, "FanSpeedRatio", "Fan speed ratio [-] (0.4-1.0)", 1.0, 95, true);
      addAnalog(103, "OADamperPosition", "Outdoor air damper position [0-1]", 1.0, 95, true);
      addBinary(104, "AHUOnOff", "AHU on/off", true, true);
      addAnalog(105, "OperationMode", "Operation mode (0=auto by calendar, 1=cooling, 2=heating)", 0, 95, true);
      addBinary(106, "HEXBypass", "Total heat exchanger bypass", false, true);
      addBinary(107, "HumidifierEnabled", "Humidifier enabled", true, true);
      addAnalog(108, "HumiditySetPoint", "Humidification on/off control setpoint RH [%]", 40, 29, true);
      addAnalog(109, "HumidityDeadband", "Humidification on/off control deadband [%]", 10, 29, true);
      //計測量（読取専用）
      addAnalog(201, "RoomTemperature", "Room dry-bulb temperature [C]", 22, 62, false);
      addAnalog(202, "RoomRelativeHumidity", "Room relative humidity [%]", 50, 29, false);
      addAnalog(203, "RoomCO2Level", "Room CO2 level [ppm]", 420, 96, false);
      addAnalog(204, "RoomPMV", "PMV [-] (before bias adjustment)", 0, 95, false);
      addAnalog(205, "RoomPPD", "PPD [%] (after bias adjustment)", 5, 98, false);
      addAnalog(206, "OccupantCount", "Number of occupants", 0, 95, false);
      addAnalog(211, "SupplyAirTemperature", "Supply air temperature [C]", 22, 62, false);
      addAnalog(212, "SupplyAirRelativeHumidity", "Supply air relative humidity [%]", 50, 29, false);
      addAnalog(213, "SupplyAirFlowRate", "Supply air flow rate [m3/h]", 0, 135, false);
      addAnalog(214, "OutdoorAirFlowRate", "Outdoor air intake flow rate [m3/h]", 0, 135, false);
      addAnalog(217, "WaterInletTemperature", "Chilled/hot water inlet temperature [C]", 7, 62, false);
      addAnalog(218, "WaterFlowRate", "Chilled/hot water flow rate [L/min]", 0, 88, false);
      addAnalog(219, "CoilLoad", "Coil load [kW]", 0, 48, false);
      addAnalog(220, "FanElectricity", "Fan electricity (supply + return) [kW]", 0, 48, false);
      addAnalog(221, "OutdoorTemperature", "Outdoor dry-bulb temperature [C]", 20, 62, false);
      addAnalog(222, "OutdoorRelativeHumidity", "Outdoor relative humidity [%]", 50, 29, false);
      addBinary(224, "HumidifierStatus", "Humidifier operating status", false, false);
      //KPI（読取専用）
      addAnalog(231, "IntegratedEnergy", "Integrated energy [kWh]", 0, 19, false);
      addAnalog(232, "IntegratedPPD", "Integrated PPD during occupancy [%h]", 0, 95, false);
      addAnalog(233, "IntegratedOccupantWeightedPPD", "Occupant-weighted integrated PPD [person %h]", 0, 95, false);
      addAnalog(234, "CO2ExcessTime", "Integrated time with CO2 > 1000 ppm during occupancy [h]", 0, 71, false);
      addAnalog(235, "OccupiedTime", "Integrated occupied time [h] (for averaged PPD)", 0, 71, false);
      //シミュレーション管理
      addAnalog(301, "AccelerationRate", "Acceleration rate (0 = pause)", s.AccelerationRate, 95, true);
      addString(302, "PauseAtDateTime", "Pause-at time (yyyy/MM/dd HH:mm:ss)",
        svc.PauseAtDateTime?.ToString("yyyy/MM/dd HH:mm:ss") ?? "");
      addString(303, "CurrentDateTime", "Current simulation time", "");
      addBinary(304, "Reinitialize", "Reinitialize (write active to reload setting.ini and restart)", false, true);

      storage.ChangeOfValue += onStorageChanged;
      //一時停止到達時は全ポイントを即時同期する（500ms周期の同期を待つと、
      //全速モードでは停止直後の読み取りが古い計測値になり制御を誤らせる）
      svc.PauseReached += syncFromEmulator;

      syncTimer = new System.Timers.Timer(500);
      syncTimer.Elapsed += (o, e) => syncFromEmulator();
      syncTimer.Start();
      syncFromEmulator();
    }

    #region オブジェクト生成・読み書きヘルパ

    private static Property MakeProp(BacnetPropertyIds id, BacnetApplicationTags tag, string value)
    { return new Property { Id = id, Tag = tag, Value = new[] { value } }; }

    private void addObj(uint instance, BacnetObjectTypes type, int typeNum, string name, string description,
      BacnetApplicationTags pvTag, string pvValue, ushort? unit)
    {
      List<Property> props = new List<Property>
      {
        MakeProp(BacnetPropertyIds.PROP_OBJECT_IDENTIFIER, BacnetApplicationTags.BACNET_APPLICATION_TAG_OBJECT_ID, $"{type}:{instance}"),
        MakeProp(BacnetPropertyIds.PROP_OBJECT_NAME, BacnetApplicationTags.BACNET_APPLICATION_TAG_CHARACTER_STRING, name),
        MakeProp(BacnetPropertyIds.PROP_OBJECT_TYPE, BacnetApplicationTags.BACNET_APPLICATION_TAG_ENUMERATED, typeNum.ToString()),
        MakeProp(BacnetPropertyIds.PROP_DESCRIPTION, BacnetApplicationTags.BACNET_APPLICATION_TAG_CHARACTER_STRING, description),
        MakeProp(BacnetPropertyIds.PROP_PRESENT_VALUE, pvTag, pvValue),
        MakeProp(BacnetPropertyIds.PROP_STATUS_FLAGS, BacnetApplicationTags.BACNET_APPLICATION_TAG_BIT_STRING, "0000"),
      };
      if (unit.HasValue)
        props.Add(MakeProp(BacnetPropertyIds.PROP_UNITS, BacnetApplicationTags.BACNET_APPLICATION_TAG_ENUMERATED, unit.Value.ToString()));
      comm.Storage.AddObject(new System.IO.BACnet.Storage.Object
      { Instance = instance, Type = type, Properties = props.ToArray() });
    }

    private void addAnalog(uint instance, string name, string desc, double value, ushort unit, bool writable)
    {
      addObj(instance, BacnetObjectTypes.OBJECT_ANALOG_VALUE, 2, name, desc,
        BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, value.ToString("R", CultureInfo.InvariantCulture), unit);
    }

    private void addBinary(uint instance, string name, string desc, bool value, bool writable)
    {
      addObj(instance, BacnetObjectTypes.OBJECT_BINARY_VALUE, 5, name, desc,
        BacnetApplicationTags.BACNET_APPLICATION_TAG_ENUMERATED, value ? "1" : "0", null);
    }

    private void addString(uint instance, string name, string desc, string value)
    {
      addObj(instance, BacnetObjectTypes.OBJECT_CHARACTERSTRING_VALUE, 40, name, desc,
        BacnetApplicationTags.BACNET_APPLICATION_TAG_CHARACTER_STRING, value, null);
    }

    private double readAnalog(uint instance, BacnetObjectTypes type)
    {
      BacnetObjectId oid = new BacnetObjectId(type, instance);
      comm.Storage.ReadProperty(oid, BacnetPropertyIds.PROP_PRESENT_VALUE,
        System.IO.BACnet.Serialize.ASN1.BACNET_ARRAY_ALL, out IList<BacnetValue> val);
      return Convert.ToDouble(val[0].Value, CultureInfo.InvariantCulture);
    }

    private void writeValue(uint instance, BacnetObjectTypes type, BacnetValue bv)
    {
      applying = true;
      try
      {
        comm.Storage.WriteProperty(new BacnetObjectId(type, instance),
          BacnetPropertyIds.PROP_PRESENT_VALUE, System.IO.BACnet.Serialize.ASN1.BACNET_ARRAY_ALL,
          new BacnetValue[] { bv }, true);
      }
      finally { applying = false; }
    }

    private void writeAnalog(uint instance, double v)
    { writeValue(instance, BacnetObjectTypes.OBJECT_ANALOG_VALUE, new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, (float)v)); }

    private void writeBinary(uint instance, bool v)
    { writeValue(instance, BacnetObjectTypes.OBJECT_BINARY_VALUE, new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_ENUMERATED, (uint)(v ? 1 : 0))); }

    private void writeString(uint instance, string v)
    { writeValue(instance, BacnetObjectTypes.OBJECT_CHARACTERSTRING_VALUE, new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_CHARACTER_STRING, v)); }

    #endregion

    #region 外部書込みの反映（BACnetクライアント→エミュレータ）

    private void onStorageChanged(DeviceStorage sender, BacnetObjectId objectId, BacnetPropertyIds propertyId, uint arrayIndex, IList<BacnetValue> value)
    {
      if (applying || propertyId != BacnetPropertyIds.PROP_PRESENT_VALUE) return;
      if (objectId.Instance < 100) return;
      double dv = 0; string sv = "";
      try { if (value.Count > 0) { sv = value[0].Value?.ToString() ?? ""; dv = Convert.ToDouble(value[0].Value, CultureInfo.InvariantCulture); } }
      catch { }
      if (Settings.Instance.LogBACnetWrites &&
        writableNames.TryGetValue(objectId.Instance, out string? wName))
        Console.WriteLine($"[BACnet write] {wName}({objectId.Instance}) = {sv}");

      lock (svc.LockObj)
      {
        AirHandlingUnitModel ahu = svc.Emulator.AHU;
        switch (objectId.Instance)
        {
          case 101: ahu.WaterValvePosition = dv; break;
          case 102: ahu.FanSpeedRatio = dv; break;
          case 103: ahu.OADamperPosition = dv; break;
          case 104: ahu.IsOn = dv != 0; break;
          case 105:
            svc.Emulator.AutoModeByCalendar = dv == 0;
            if (dv == 1) ahu.IsCoolingMode = true;
            if (dv == 2) ahu.IsCoolingMode = false;
            break;
          case 106: ahu.BypassHEX = dv != 0; break;
          case 107: ahu.HumidifierEnabled = dv != 0; break;
          case 108: ahu.HumiditySetPoint = dv; break;
          case 109: ahu.HumidityDeadband = dv; break;
          case 301: svc.AccelerationRate = (uint)Math.Max(0, dv); break;
          case 302:
            if (DateTime.TryParse(sv, CultureInfo.InvariantCulture, DateTimeStyles.None, out DateTime pAt))
              svc.PauseAtDateTime = pAt;
            else svc.PauseAtDateTime = null;
            break;
          case 304:
            if (dv != 0)
            {
              //リセット中はCurrentDateTimeを空にする（クライアントが完了を検知できるようにする）
              writeString(303, "");
              svc.Reset();
              writeBinary(304, false);
            }
            break;
        }
      }
    }

    #endregion

    #region 計測値の同期（エミュレータ→BACnet）

    private void syncFromEmulator()
    {
      lock (svc.LockObj)
      {
        Shizuku3Emulator emu = svc.Emulator;
        Popolo.Core.Building.IReadOnlyZone zn = emu.Load.Zone;
        double rh = Popolo.Core.Physics.MoistAir.GetRelativeHumidityFromDryBulbTemperatureAndHumidityRatio(
          zn.Temperature, zn.HumidityRatio, Popolo.Core.Physics.PhysicsConstants.StandardAtmosphericPressure);
        double oaRh = Popolo.Core.Physics.MoistAir.GetRelativeHumidityFromDryBulbTemperatureAndHumidityRatio(
          emu.OutdoorTemperature, emu.OutdoorHumidityRatio, Popolo.Core.Physics.PhysicsConstants.StandardAtmosphericPressure);

        //温度は小数点第1位、相対湿度は整数に丸めて公開する
        writeAnalog(201, Math.Round(zn.Temperature, 1));
        writeAnalog(202, Math.Round(rh));
        writeAnalog(203, emu.Load.CO2Level_PPM);
        writeAnalog(204, emu.PMV);
        writeAnalog(205, emu.PPD);
        writeAnalog(206, emu.Load.StayWorkerCount);
        writeAnalog(211, Math.Round(emu.AHU.SupplyAirTemperature, 1));
        writeAnalog(212, Math.Round(Popolo.Core.Physics.MoistAir.GetRelativeHumidityFromDryBulbTemperatureAndHumidityRatio(
          emu.AHU.SupplyAirTemperature, emu.AHU.SupplyAirHumidityRatio,
          Popolo.Core.Physics.PhysicsConstants.StandardAtmosphericPressure)));
        writeAnalog(213, 3600 * emu.AHU.SupplyAirVolumetricFlowRate);
        writeAnalog(214, 3600 * emu.AHU.OAVolumetricFlowRate);
        writeAnalog(217, Math.Round(emu.AHU.IsCoolingMode ? emu.ChilledWaterTemperature : emu.HotWaterTemperature, 1));
        writeAnalog(218, emu.AHU.WaterFlowRate);
        writeAnalog(219, emu.AHU.CoilLoad);
        writeAnalog(220, emu.AHU.FanElectricity);
        writeAnalog(221, Math.Round(emu.OutdoorTemperature, 1));
        writeAnalog(222, Math.Round(oaRh));
        writeBinary(224, emu.AHU.HumidifierOn);
        writeAnalog(231, emu.IntegratedEnergy_kWh);
        writeAnalog(232, emu.IntegratedPPD);
        writeAnalog(233, emu.IntegratedOccupantWeightedPPD);
        writeAnalog(234, emu.CO2ExcessTime_h);
        writeAnalog(235, emu.OccupiedTime_h);
        writeAnalog(301, svc.AccelerationRate); //自停止（0化）をクライアントへ反映
        writeString(303, emu.CurrentDateTime.ToString("yyyy/MM/dd HH:mm:ss"));
      }
    }

    #endregion

  }
}

