using Popolo.Core.Building;
using Popolo.Core.Climate;
using Popolo.Core.Numerics;
using Popolo.Core.Physics;
using Popolo.Core.ThermalComfort;

namespace Shizuku3
{
  /// <summary>Shizuku3エミュレータ本体（建物+空調機+外乱3系統+KPI。BACnet層は含まない）</summary>
  /// <remarks>
  /// ・外乱系統1: RandomWeather（VARモデル）による確率的気象。直散分離と夜間放射は本クラスで計算
  /// ・外乱系統2: 執務者（HeatLoadModel内のOfficeTenant）
  /// ・外乱系統3: 冷温水入口温度のAR(1)（Ornstein-Uhlenbeck）過程
  /// ・初期化: 開始日前日を空調停止・Δt=3600sで収束するまで繰り返す周期定常計算（自然室温）
  /// ・KPI: エネルギー（コイル熱量/COP+ファン電力）、在室時PPD積算（単純・人数重み）、CO2超過時間
  /// 操作量はAHUプロパティ経由で外部（将来はBACnet層）から与える。
  /// </remarks>
  public class Shizuku3Emulator
  {

    #region 評価・外乱パラメータ（setting.iniから読込）

    /// <summary>冷却系システムCOP[-]</summary>
    public static double SYSTEM_COP_COOLING { get { return Settings.Instance.SystemCOPCooling; } }

    /// <summary>加熱系システムCOP[-]</summary>
    public static double SYSTEM_COP_HEATING { get { return Settings.Instance.SystemCOPHeating; } }

    /// <summary>PMVバイアス[-]</summary>
    public static double PMV_BIAS { get { return Settings.Instance.PMVBias; } }

    private static double CHW_MEAN { get { return Settings.Instance.CHWTempMean; } }
    private static double CHW_STDEV { get { return Settings.Instance.CHWTempStDev; } }
    private static double CHW_CORR_TIME { get { return Settings.Instance.CHWTempCorrTime; } }
    private static double HW_MEAN { get { return Settings.Instance.HWTempMean; } }
    private static double HW_STDEV { get { return Settings.Instance.HWTempStDev; } }
    private static double HW_CORR_TIME { get { return Settings.Instance.HWTempCorrTime; } }

    /// <summary>助走計算の収束判定[K]と最大反復回数</summary>
    private const double PRECOND_TOLERANCE = 0.01;
    private const int PRECOND_MAX_CYCLES = 50;

    #endregion

    #region プロパティ・インスタンス変数

    /// <summary>熱負荷計算モデル（建物+執務者+CO2）</summary>
    public HeatLoadModel Load { get; }

    /// <summary>空調機モデル（操作量はこのプロパティ経由で設定する）</summary>
    public AirHandlingUnitModel AHU { get; }

    /// <summary>現在のシミュレーション日時</summary>
    public DateTime CurrentDateTime { get; private set; }

    /// <summary>外気温度[C]/外気絶対湿度[kg/kg]</summary>
    public double OutdoorTemperature { get; private set; }
    public double OutdoorHumidityRatio { get; private set; }

    /// <summary>冷水・温水入口温度[C]（AR(1)外乱）</summary>
    public double ChilledWaterTemperature { get; private set; }
    public double HotWaterTemperature { get; private set; }

    /// <summary>現在のPMV[-]（バイアス適用前）とPPD[%]（バイアス適用後）</summary>
    public double PMV { get; private set; }
    public double PPD { get; private set; }

    /// <summary>KPI積算値</summary>
    public double IntegratedEnergy_kWh { get; private set; }
    public double IntegratedPPD { get; private set; }         //[%・h]
    public double IntegratedOccupantWeightedPPD { get; private set; } //[人・%・h]
    public double CO2ExcessTime_h { get; private set; }
    public double OccupiedTime_h { get; private set; } //在室時間積算（平均PPD算出用）

    /// <summary>助走計算の反復回数（収束確認用）</summary>
    public int PreconditionCycles { get; private set; }

    /// <summary>冷暖モードを月で自動決定するか（falseならAHU.IsCoolingModeを直接操作）</summary>
    public bool AutoModeByCalendar { get; set; } = true;

    private readonly double timeStep;
    private readonly uint occupantSeed;
    private readonly Sun sun;
    private readonly NormalRandom waterRnd;
    private readonly double[] wDbt, wHum, wRad; //1時間毎1年分
    private readonly bool[] wFair;

    #endregion

    #region コンストラクタ

    /// <summary>エミュレータを作成し、助走計算により自然室温へ初期化する</summary>
    /// <param name="timeStep">計算時間刻み[sec]（1-60）</param>
    /// <param name="startDateTime">開始日時</param>
    /// <param name="weatherSeed">気象乱数シード（系統1）</param>
    /// <param name="occupantSeed">執務者乱数シード（系統2）</param>
    /// <param name="waterTempSeed">冷温水温度乱数シード（系統3）</param>
    public Shizuku3Emulator(double timeStep, DateTime startDateTime,
      uint weatherSeed, uint occupantSeed, uint waterTempSeed)
    {
      if (timeStep <= 0 || 60 < timeStep)
        throw new ArgumentOutOfRangeException(nameof(timeStep), "計算時間刻みは1～60secとすること");
      this.timeStep = timeStep;
      this.occupantSeed = occupantSeed;

      Load = new HeatLoadModel(timeStep, occupantSeed);
      AHU = new AirHandlingUnitModel();
      sun = new Sun(Sun.City.Tokyo);
      waterRnd = new NormalRandom(waterTempSeed);
      ChilledWaterTemperature = CHW_MEAN;
      HotWaterTemperature = HW_MEAN;

      if (!Enum.TryParse(Settings.Instance.WeatherLocation, out RandomWeather.Location loc))
        loc = RandomWeather.Location.Tokyo;
      RandomWeather rWeather = new RandomWeather(weatherSeed, loc);
      rWeather.MakeWeather(1, out wDbt, out wHum, out wRad, out wFair);

      CurrentDateTime = startDateTime;
      Precondition(startDateTime);
    }

    #endregion

    #region 公開メソッド

    /// <summary>KPI積算値をクリアする</summary>
    public void ClearKPI()
    {
      IntegratedEnergy_kWh = IntegratedPPD = IntegratedOccupantWeightedPPD = CO2ExcessTime_h = OccupiedTime_h = 0;
    }

    /// <summary>1計算刻み進める</summary>
    public void Step()
    {
      UpdateOutdoorCondition(CurrentDateTime);
      UpdateWaterTemperatures();
      Load.Update(CurrentDateTime);

      //空調機（冷暖モードはカレンダー自動: 5-10月冷房）
      IReadOnlyZone zone = Load.Zone;
      if (AutoModeByCalendar)
        AHU.IsCoolingMode = 5 <= CurrentDateTime.Month && CurrentDateTime.Month <= 10;
      AHU.ChilledWaterInletTemperature = ChilledWaterTemperature;
      AHU.HotWaterInletTemperature = HotWaterTemperature;
      AHU.Update(zone.Temperature, zone.HumidityRatio, OutdoorTemperature, OutdoorHumidityRatio);

      //建物へ給気を接続して状態更新
      Load.Building.SetSupplyAir(0, 0,
        AHU.SupplyAirTemperature, AHU.SupplyAirHumidityRatio, AHU.SupplyAirMassFlowRate);
      Load.Building.ForecastHeatTransfer();
      Load.Building.ForecastWaterTransfer();
      Load.Building.FixState();

      //CO2（外気導入はB系統として接続）
      Load.SetOutdoorAirSupply(AHU.OAVolumetricFlowRate);
      Load.UpdateCO2();

      UpdateKPI();
      CurrentDateTime = CurrentDateTime.AddSeconds(timeStep);
    }

    #endregion

    #region privateメソッド

    /// <summary>気象を更新する（1時間データから線形補間、直散分離、夜間放射）</summary>
    private void UpdateOutdoorCondition(DateTime dTime)
    {
      //時系列位置（うるう年2/29は2/28と同値で代用）
      int day = Math.Min(364, dTime.DayOfYear - 1);
      double hPos = day * 24 + dTime.Hour + dTime.Minute / 60d + dTime.Second / 3600d;
      int h0 = (int)hPos;
      double rate = hPos - h0;
      int h1 = (h0 + 1) % 8760;
      h0 %= 8760;

      double dbt = wDbt[h0] * (1 - rate) + wDbt[h1] * rate;
      double hum = 0.001 * (wHum[h0] * (1 - rate) + wHum[h1] * rate); //[g/kg]→[kg/kg]
      double ghr = Math.Max(0, wRad[h0] * (1 - rate) + wRad[h1] * rate);

      sun.Update(dTime);
      if (0 < sun.Altitude && 0 < ghr)
        sun.SeparateGlobalHorizontalRadiation(ghr, Sun.SeparationMethod.Erbs);
      else sun.SetGlobalHorizontalRadiation(0, 0);

      //夜間放射（雲量は晴天フラグから近似: 晴天2、曇天8）
      int cloudCover = wFair[h0] ? 2 : 8;
      double pv = 101.325 * hum / (0.622 + hum); //水蒸気分圧[kPa]
      double nr = Sky.GetNocturnalRadiation(dbt, cloudCover, pv);

      Load.Building.UpdateOutdoorCondition(dTime, sun, dbt, hum, nr);
      OutdoorTemperature = dbt;
      OutdoorHumidityRatio = hum;
    }

    /// <summary>冷温水入口温度をAR(1)（Ornstein-Uhlenbeck）過程で更新する</summary>
    private void UpdateWaterTemperatures()
    {
      double phiC = Math.Exp(-timeStep / CHW_CORR_TIME);
      double phiH = Math.Exp(-timeStep / HW_CORR_TIME);
      ChilledWaterTemperature = CHW_MEAN + (ChilledWaterTemperature - CHW_MEAN) * phiC
        + CHW_STDEV * Math.Sqrt(1 - phiC * phiC) * waterRnd.NextDouble_Standard();
      HotWaterTemperature = HW_MEAN + (HotWaterTemperature - HW_MEAN) * phiH
        + HW_STDEV * Math.Sqrt(1 - phiH * phiH) * waterRnd.NextDouble_Standard();
    }

    /// <summary>KPIを更新する</summary>
    private void UpdateKPI()
    {
      double dtH = timeStep / 3600d;
      double cop = AHU.IsCoolingMode ? SYSTEM_COP_COOLING : SYSTEM_COP_HEATING;
      IntegratedEnergy_kWh += (AHU.CoilLoad / cop + AHU.FanElectricity) * dtH;

      IReadOnlyZone zone = Load.Zone;
      double rh = MoistAir.GetRelativeHumidityFromDryBulbTemperatureAndHumidityRatio(
        zone.Temperature, zone.HumidityRatio, PhysicsConstants.StandardAtmosphericPressure);
      double clo = 0.7;
      int mm = CurrentDateTime.Month;
      if (6 <= mm && mm <= 9) clo = 0.5;
      else if (mm <= 3 || mm == 12) clo = 1.0;
      PMV = FangerModel.GetPMV(zone.Temperature, zone.GetMeanSurfaceTemperature(), rh, 0.1, clo, 1.1, 0);
      PPD = FangerModel.GetPPD(PMV - PMV_BIAS);

      uint stay = Load.StayWorkerCount;
      if (0 < stay)
      {
        OccupiedTime_h += dtH;
        IntegratedPPD += PPD * dtH;
        IntegratedOccupantWeightedPPD += PPD * stay * dtH;
        if (1000 < Load.CO2Level_PPM) CO2ExcessTime_h += dtH;
      }
    }

    /// <summary>開始日前日の繰り返しによる周期定常計算で自然室温に初期化する</summary>
    private void Precondition(DateTime startDateTime)
    {
      Load.Building.TimeStep = 3600;
      DateTime prevDay = startDateTime.Date.AddDays(-1);
      double lastEndTemp = double.MaxValue, lastEndSrfTemp = double.MaxValue;

      for (PreconditionCycles = 1; PreconditionCycles <= PRECOND_MAX_CYCLES; PreconditionCycles++)
      {
        for (int h = 0; h < 24; h++)
        {
          DateTime t = prevDay.AddHours(h);
          UpdateOutdoorCondition(t);
          //前日は休日相当（無人・内部発熱なし）と想定し、空調停止で自然室温とする
          Load.Building.SetBaseHeatGain(0, 0, 0, 0, 0);
          Load.Building.SetSupplyAir(0, 0, 22, 0.0105, 0);
          Load.Building.ForecastHeatTransfer();
          Load.Building.ForecastWaterTransfer();
          Load.Building.FixState();
        }
        double endTemp = Load.Zone.Temperature;
        double endSrfTemp = Load.Zone.GetMeanSurfaceTemperature();
        bool converged = Math.Abs(endTemp - lastEndTemp) < PRECOND_TOLERANCE
          && Math.Abs(endSrfTemp - lastEndSrfTemp) < PRECOND_TOLERANCE;
        lastEndTemp = endTemp;
        lastEndSrfTemp = endSrfTemp;
        if (converged) break;
      }
      PreconditionCycles = Math.Min(PreconditionCycles, PRECOND_MAX_CYCLES);

      Load.Building.TimeStep = timeStep;
      Load.ResetTenant(); //本計算用に執務者の乱数系列を初期化（助走計算は無人のため未使用）
    }

    #endregion

  }
}
