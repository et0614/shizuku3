using Popolo.Core.Building;
using Popolo.Core.Building.AirQuality;
using Popolo.Core.OccupantBehavior;
using Popolo.Core.Physics;

namespace Shizuku3
{
  /// <summary>Shizuku3の熱負荷計算モデル（建物+執務者+内部発熱+CO2濃度）</summary>
  /// <remarks>
  /// 仕様は docs「01_物理モデル諸元.md」§3・§6に従う。
  /// ・執務者: Popolo3 OfficeWorkerの確率モデル（出退勤=正規分布、在離席=マルコフ連鎖）。
  /// 　人数は床面積と業種から確率的に生成される。人体は定数発熱（2ノードモデル不使用）
  /// ・照明: 在館時点灯（誰かが在館していれば点灯、調光なし）
  /// ・機器: 在席者比例+待機分
  /// ・CO2: MultiZoneCO2Model（単一ゾーン+外気、漏気はZone.VentilationRateから自動反映）
  /// 　※機械換気（外気導入）は空調機モデル実装後にAuxiliaryVentilationRateで接続する
  /// 呼び出し順: 気象更新 → Update(dTime) → ForecastHeatTransfer/WaterTransfer → FixState → UpdateCO2()
  /// </remarks>
  public class HeatLoadModel
  {

    #region 内部発熱条件（setting.iniから読込）

    /// <summary>執務者1人あたり顕熱[W]（約1.1met事務作業相当）</summary>
    public static double OCCUPANT_SHEAT_GAIN { get { return Settings.Instance.OccupantSensibleHeatGain; } }

    /// <summary>執務者1人あたり潜熱[W]</summary>
    public static double OCCUPANT_LHEAT_GAIN { get { return Settings.Instance.OccupantLatentHeatGain; } }

    /// <summary>照明発熱[W/m2]（在館時点灯・調光なし）</summary>
    public static double LIGHT_HEAT_GAIN { get { return Settings.Instance.LightHeatGain; } }

    /// <summary>機器発熱[W/人]（在席時）</summary>
    public static double PLUG_HEAT_GAIN_PERSON { get { return Settings.Instance.PlugHeatGainPerson; } }

    /// <summary>機器待機発熱[W/m2]（常時）</summary>
    public static double PLUG_HEAT_GAIN_BASE { get { return Settings.Instance.PlugHeatGainBase; } }

    /// <summary>内部発熱の放射成分比率[-]</summary>
    public static double RADIATIVE_HEAT_GAIN_RATE { get { return Settings.Instance.RadiativeHeatGainRate; } }

    /// <summary>外気CO2濃度[ppm]</summary>
    public static double OUTDOOR_CO2_PPM { get { return Settings.Instance.OutdoorCO2PPM; } }

    #endregion

    #region インスタンス変数・プロパティ

    /// <summary>建物熱モデル</summary>
    public BuildingThermalModel Building { get; }

    /// <summary>執務者（テナント）モデル</summary>
    public OfficeTenant Tenant { get; private set; }

    /// <summary>執務者乱数シード</summary>
    private readonly uint occupantSeed;

    /// <summary>CO2濃度計算モデル</summary>
    public MultiZoneCO2Model CO2Model { get; }

    /// <summary>CO2計算ゾーン</summary>
    private readonly CO2ModelZone co2Zone;

    /// <summary>日次スケジュールを更新した日付</summary>
    private DateTime lastScheduledDate = DateTime.MinValue;

    /// <summary>ゾーン（単一）</summary>
    public IReadOnlyZone Zone { get { return Building.MultiRoom[0].Zones[0]; } }

    /// <summary>在室人数[人]</summary>
    public uint StayWorkerCount { get { return Tenant.StayWorkerCount; } }

    /// <summary>室CO2濃度[ppm]</summary>
    public double CO2Level_PPM { get { return co2Zone.CO2Level_PPM; } }

    /// <summary>現在の顕熱内部発熱[W]（対流+放射）</summary>
    public double SensibleHeatGain { get; private set; }

    /// <summary>現在の潜熱内部発熱（水蒸気供給量）[kg/s]</summary>
    public double LatentHeatGain { get; private set; }

    #endregion

    #region コンストラクタ

    /// <summary>熱負荷計算モデルを作成する</summary>
    /// <param name="timeStep">計算時間刻み[sec]</param>
    /// <param name="occupantSeed">執務者乱数シード（乱数系統2）</param>
    public HeatLoadModel(double timeStep, uint occupantSeed)
    {
      Building = BuildingModelBuilder.Make(timeStep);
      this.occupantSeed = occupantSeed;
      ResetTenant();

      co2Zone = new CO2ModelZone(Zone);
      co2Zone.CO2Level = OUTDOOR_CO2_PPM * 1e-6;
      CO2Model = new MultiZoneCO2Model(new CO2ModelZone[] { co2Zone }, Building);
      CO2Model.OutdoorCO2Level = OUTDOOR_CO2_PPM * 1e-6;
    }

    #endregion

    #region 公開メソッド

    /// <summary>執務者モデルをシードから再生成する（助走計算の決定論的反復・リセット用）</summary>
    public void ResetTenant()
    {
      //執務者数は床面積と業種（setting.ini指定）の在籍密度モデルから確率的に生成される
      if (!Enum.TryParse(Settings.Instance.OccupantIndustry, out OfficeTenant.CategoryOfIndustry industry))
        industry = OfficeTenant.CategoryOfIndustry.InformationAndCommunications;
      Tenant = new OfficeTenant(industry, BuildingModelBuilder.FLOOR_AREA,
        OfficeTenant.DaysOfWeek.Saturday | OfficeTenant.DaysOfWeek.Sunday, occupantSeed);
      lastScheduledDate = DateTime.MinValue;
    }

    /// <summary>空調機からの外気導入量をCO2モデルに設定する</summary>
    /// <param name="oaVolumetricFlowRate">外気導入体積流量[m3/s]</param>
    public void SetOutdoorAirSupply(double oaVolumetricFlowRate)
    {
      co2Zone.AuxiliaryVentilationRate = oaVolumetricFlowRate;
      co2Zone.AuxiliaryVentilationCO2Level = OUTDOOR_CO2_PPM * 1e-6;
    }

    /// <summary>在室状態に応じて内部発熱とCO2発生量を設定する</summary>
    /// <param name="dTime">現在日時</param>
    /// <remarks>気象条件の更新後、ForecastHeatTransferの前に毎ステップ呼ぶ</remarks>
    public void Update(DateTime dTime)
    {
      //日付が変わったら執務者の日次スケジュール（出退勤・休暇）を更新
      if (lastScheduledDate != dTime.Date)
      {
        Tenant.UpdateDailySchedule(dTime);
        lastScheduledDate = dTime.Date;
      }
      Tenant.UpdateStatus(dTime);
      int stayCount = (int)Tenant.StayWorkerCount;

      double fArea = BuildingModelBuilder.FLOOR_AREA;
      double lightGain = (0 < stayCount) ? LIGHT_HEAT_GAIN * fArea : 0;
      double plugGain = PLUG_HEAT_GAIN_PERSON * stayCount + PLUG_HEAT_GAIN_BASE * fArea;
      double sGain = lightGain + plugGain + OCCUPANT_SHEAT_GAIN * stayCount;
      double lGain = OCCUPANT_LHEAT_GAIN * stayCount / (1000 * Water.VaporizationHeatAtTriplePoint);
      Building.SetBaseHeatGain(0, 0,
        (1 - RADIATIVE_HEAT_GAIN_RATE) * sGain, RADIATIVE_HEAT_GAIN_RATE * sGain, lGain);
      SensibleHeatGain = sGain;
      LatentHeatGain = lGain;

      co2Zone.CO2Generation = CO2Balance.StandardCO2GenerationRatePerPerson * stayCount;
    }

    /// <summary>CO2濃度を1ステップ進める</summary>
    /// <remarks>建物熱モデルのFixState後に毎ステップ呼ぶ（最新の漏気・給気量を参照するため）</remarks>
    public void UpdateCO2()
    {
      CO2Model.Update(Building.TimeStep);
    }

    #endregion

  }
}
