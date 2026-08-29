using System.Globalization;

namespace Shizuku3
{
  /// <summary>setting.ini（KEY=value; コメント 形式）の読込。ファイルが無い項目は既定値を使う</summary>
  public class Settings
  {

    #region シングルトン

    private static Settings? instance;

    /// <summary>設定（初回参照時に実行ファイルと同じフォルダのsetting.iniを読み込む）</summary>
    public static Settings Instance
    { get { return instance ??= new Settings(Path.Combine(AppContext.BaseDirectory, "setting.ini")); } }

    /// <summary>設定を再読込する（リセット時に使用）</summary>
    public static void Reload()
    { instance = null; }

    #endregion

    #region 設定項目（既定値は docs「02_設定ファイル仕様.md」に従う）

    //実行制御
    public uint AccelerationRate { get; private set; } = 60;
    public double TimeStep { get; private set; } = 1;
    public double ControlInterval { get; private set; } = 300;
    public double ValveTravelTime { get; private set; } = 90;
    public bool LogBACnetWrites { get; private set; } = true;
    public DateTime SimulationStartDate { get; private set; } = new DateTime(2026, 8, 5);
    public int SimulationDays { get; private set; } = 1;
    public double DataOutputSpan { get; private set; } = 1;

    //BACnet
    public string LocalEndpoint { get; private set; } = "127.0.0.1";
    public uint DeviceID { get; private set; } = 3000;
    public int UdpPort { get; private set; } = 47808;

    //エネルギー・快適性評価
    public double SystemCOPCooling { get; private set; } = 3.5;
    public double SystemCOPHeating { get; private set; } = 0.85;
    public double PumpWTF { get; private set; } = 40;
    public double PMVBias { get; private set; } = 0.0;
    public bool PPDOccupantWeighted { get; private set; } = false;

    //乱数系統1: 気象
    public uint WeatherSeed { get; private set; } = 1;
    public string WeatherLocation { get; private set; } = "Tokyo";

    //乱数系統2: 執務者
    public uint OccupantSeed { get; private set; } = 2;
    public string OccupantIndustry { get; private set; } = "InformationAndCommunications";
    public double OccupantSensibleHeatGain { get; private set; } = 60;
    public double OccupantLatentHeatGain { get; private set; } = 55;

    //乱数系統3: 冷温水温度
    public uint WaterTempSeed { get; private set; } = 3;
    public double CHWTempMean { get; private set; } = 7.0;
    public double CHWTempStDev { get; private set; } = 1.0;
    public double CHWTempCorrTime { get; private set; } = 1800;
    public double HWTempMean { get; private set; } = 44.0;
    public double HWTempStDev { get; private set; } = 2.0;
    public double HWTempCorrTime { get; private set; } = 1800;

    //内部発熱
    public double LightHeatGain { get; private set; } = 12;
    public double PlugHeatGainPerson { get; private set; } = 40;
    public double PlugHeatGainBase { get; private set; } = 5;
    public double RadiativeHeatGainRate { get; private set; } = 0.4;

    //CO2
    public double OutdoorCO2PPM { get; private set; } = 420;

    #endregion

    #region 読込処理

    private Settings(string path)
    {
      if (!File.Exists(path)) return;
      Dictionary<string, string> kv = new Dictionary<string, string>();
      foreach (string line in File.ReadAllLines(path))
      {
        string body = line.Split(';')[0].Trim();
        int eq = body.IndexOf('=');
        if (eq <= 0) continue;
        kv[body.Substring(0, eq).Trim().ToUpper()] = body.Substring(eq + 1).Trim();
      }

      AccelerationRate = getUInt(kv, "ACCELERATION_RATE", AccelerationRate);
      TimeStep = Math.Max(1, Math.Min(60, getDouble(kv, "TIME_STEP", TimeStep)));
      ControlInterval = getDouble(kv, "CONTROL_INTERVAL", ControlInterval);
      ValveTravelTime = getDouble(kv, "VALVE_TRAVEL_TIME", ValveTravelTime);
      LogBACnetWrites = getString(kv, "LOG_BACNET_WRITES", "true").ToLower() != "false";
      if (kv.TryGetValue("SIMULATION_START_DATE", out string? sd) &&
        DateTime.TryParse(sd, CultureInfo.InvariantCulture, DateTimeStyles.None, out DateTime dt))
        SimulationStartDate = dt;
      SimulationDays = (int)getUInt(kv, "SIMULATION_DAYS", (uint)SimulationDays);
      DataOutputSpan = getDouble(kv, "DATA_OUTPUT_TSPAN", DataOutputSpan);
      LocalEndpoint = getString(kv, "LOCAL_ENDPOINT", LocalEndpoint);
      DeviceID = getUInt(kv, "DEVICE_ID", DeviceID);
      UdpPort = (int)getUInt(kv, "UDP_PORT", (uint)UdpPort);
      SystemCOPCooling = getDouble(kv, "SYSTEM_COP_COOLING", SystemCOPCooling);
      SystemCOPHeating = getDouble(kv, "SYSTEM_COP_HEATING", SystemCOPHeating);
      PumpWTF = Math.Max(1, getDouble(kv, "PUMP_WTF", PumpWTF));
      PMVBias = getDouble(kv, "PMV_BIAS", PMVBias);
      PPDOccupantWeighted = getString(kv, "PPD_OCCUPANT_WEIGHTED", "false").ToLower() == "true";
      WeatherSeed = getUInt(kv, "WEATHER_SEED", WeatherSeed);
      WeatherLocation = getString(kv, "WEATHER_LOCATION", WeatherLocation);
      OccupantSeed = getUInt(kv, "OCCUPANT_SEED", OccupantSeed);
      OccupantIndustry = getString(kv, "OCCUPANT_INDUSTRY", OccupantIndustry);
      OccupantSensibleHeatGain = getDouble(kv, "OCCUPANT_SHEAT_GAIN", OccupantSensibleHeatGain);
      OccupantLatentHeatGain = getDouble(kv, "OCCUPANT_LHEAT_GAIN", OccupantLatentHeatGain);
      WaterTempSeed = getUInt(kv, "WATER_TEMP_SEED", WaterTempSeed);
      CHWTempMean = getDouble(kv, "CHW_TEMP_MEAN", CHWTempMean);
      CHWTempStDev = getDouble(kv, "CHW_TEMP_STDEV", CHWTempStDev);
      CHWTempCorrTime = getDouble(kv, "CHW_TEMP_CORR_TIME", CHWTempCorrTime);
      HWTempMean = getDouble(kv, "HW_TEMP_MEAN", HWTempMean);
      HWTempStDev = getDouble(kv, "HW_TEMP_STDEV", HWTempStDev);
      HWTempCorrTime = getDouble(kv, "HW_TEMP_CORR_TIME", HWTempCorrTime);
      LightHeatGain = getDouble(kv, "LIGHT_HEAT_GAIN", LightHeatGain);
      PlugHeatGainPerson = getDouble(kv, "PLUG_HEAT_GAIN_PERSON", PlugHeatGainPerson);
      PlugHeatGainBase = getDouble(kv, "PLUG_HEAT_GAIN_BASE", PlugHeatGainBase);
      RadiativeHeatGainRate = getDouble(kv, "RADIATIVE_HEAT_GAIN_RATE", RadiativeHeatGainRate);
      OutdoorCO2PPM = getDouble(kv, "OUTDOOR_CO2_PPM", OutdoorCO2PPM);
    }

    private static string getString(Dictionary<string, string> kv, string key, string def)
    { return kv.TryGetValue(key, out string? v) ? v : def; }

    private static double getDouble(Dictionary<string, string> kv, string key, double def)
    { return kv.TryGetValue(key, out string? v) && double.TryParse(v, CultureInfo.InvariantCulture, out double d) ? d : def; }

    private static uint getUInt(Dictionary<string, string> kv, string key, uint def)
    { return kv.TryGetValue(key, out string? v) && uint.TryParse(v, out uint d) ? d : def; }

    #endregion

  }
}



