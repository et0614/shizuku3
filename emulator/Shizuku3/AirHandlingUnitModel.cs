using Popolo.Core.HVAC.AirSide;
using Popolo.Core.HVAC.FluidCircuit;
using Popolo.Core.HVAC.HeatExchanger;
using Popolo.Core.Physics;

namespace Shizuku3
{
  /// <summary>Shizuku3の空調機（AHU）モデル。Shizuku1基準階南側ペリメータ担当機（ahuNumber=2）を踏襲</summary>
  /// <remarks>
  /// 制御器を含まない物理モデル。操作量（弁開度・ファン回転数比・外気ダンパ開度・冷暖モード・
  /// 全熱交バイパス・加湿有効）を外部から与え、給気状態と風量・水量・消費電力を返す。
  /// ・風量: VAVなし単一ダクトのため回路網は使わない。給気風量はファン相似則（風量∝回転数比、
  /// 　消費電力∝回転数比^3）、外気量は外気枝（ダクト+ダンパ+全熱交）の単枝抵抗計算による
  /// ・冷温水弁: 二方弁、イコールパーセント特性（レンジアビリティ50）、定差圧仮定
  /// ・加湿器: 滴下浸透気化式。還気相対湿度によるOn/Off制御（設定値±幅、暖房時のみ）を内蔵
  /// </remarks>
  public class AirHandlingUnitModel
  {

    #region 定格定数（Shizuku1 AirHandlingUnit.cs / AirFlowNetwork.cs 基準階南側ペリメータ機より転記）

    /// <summary>設計給気風量[CMH]</summary>
    public const double DESIGN_SA_FLOW = 5790;

    /// <summary>設計還気風量[CMH]</summary>
    public const double DESIGN_RA_FLOW = 5473;

    /// <summary>設計外気風量[CMH]</summary>
    public const double DESIGN_OA_FLOW = 870;

    /// <summary>冷水コイル設計流量[L/min]</summary>
    public const double DESIGN_CHW_FLOW = 48.6;

    /// <summary>温水コイル設計流量[L/min]</summary>
    public const double DESIGN_HW_FLOW = 25.9;

    /// <summary>定格冷却能力[kW]</summary>
    public const double DESIGN_COOLING_CAPACITY = 27.1;

    /// <summary>定格加熱能力[kW]</summary>
    public const double DESIGN_HEATING_CAPACITY = 14.5;

    /// <summary>冷温水弁のレンジアビリティ[-]</summary>
    public const double VALVE_RANGE_ABILITY = 50;

    /// <summary>ダンパのレンジアビリティ[-]</summary>
    private const double DAMPER_RANGE_ABILITY = 30;

    /// <summary>ダンパのリニア特性重み係数[-]</summary>
    private const double DAMPER_LINEAR_WEIGHT = 0.5;

    /// <summary>外気ダクトの抵抗係数[kPa/(m3/s)^2]（Shizuku1 AirFlowNetwork.cs L193のresists[3]）</summary>
    private const double OA_DUCT_RESISTANCE = 1.550;

    /// <summary>全熱交換器（給気側）の抵抗係数[kPa/(m3/s)^2]（同resists[4]。バイパス時は0）</summary>
    private const double HEX_RESISTANCE = 2.380;

    #endregion

    #region 操作量（外部制御入力）

    /// <summary>冷温水弁開度[-]（0-1）</summary>
    public double WaterValvePosition { get; set; } = 0;

    /// <summary>ファン回転数比[-]（0.4-1.0）。給気・還気連動</summary>
    public double FanSpeedRatio { get; set; } = 1.0;

    /// <summary>外気ダンパ開度[-]（0-1、排気ダンパ連動）。全開・バイパスなしで設計外気量</summary>
    public double OADamperPosition { get; set; } = 1.0;

    /// <summary>AHU発停</summary>
    public bool IsOn { get; set; } = true;

    /// <summary>冷房モードか（false=暖房）</summary>
    public bool IsCoolingMode { get; set; } = true;

    /// <summary>全熱交換器バイパス</summary>
    public bool BypassHEX { get; set; } = false;

    /// <summary>加湿器有効</summary>
    public bool HumidifierEnabled { get; set; } = true;

    /// <summary>加湿On/Off制御の設定相対湿度[%]</summary>
    public double HumiditySetPoint { get; set; } = 40;

    /// <summary>加湿On/Off制御のディファレンシャル[%]（設定値±幅）</summary>
    public double HumidityDeadband { get; set; } = 10;

    /// <summary>冷水入口温度[C]（外乱。エミュレータがAR(1)過程で更新する）</summary>
    public double ChilledWaterInletTemperature { get; set; } = 7.0;

    /// <summary>温水入口温度[C]（外乱。エミュレータがAR(1)過程で更新する）</summary>
    public double HotWaterInletTemperature { get; set; } = 44.0;

    #endregion

    #region 計算結果（読み取り）

    /// <summary>給気温度[C]</summary>
    public double SupplyAirTemperature { get; private set; } = 22;

    /// <summary>計算時間刻み[sec]（弁アクチュエータのレート制限に使用。エミュレータが設定する）</summary>
    public double TimeStep { get; set; } = 1;

    /// <summary>弁の実開度[-]（指令開度WaterValvePositionへ一定速度で移動する）</summary>
    public double ActualValvePosition { get; private set; } = 0;

    /// <summary>給気絶対湿度[kg/kg]</summary>
    public double SupplyAirHumidityRatio { get; private set; } = 0.0105;

    /// <summary>給気質量流量[kg/s]</summary>
    public double SupplyAirMassFlowRate { get; private set; }

    /// <summary>給気体積流量[m3/s]</summary>
    public double SupplyAirVolumetricFlowRate { get; private set; }

    /// <summary>外気導入体積流量[m3/s]</summary>
    public double OAVolumetricFlowRate { get; private set; }

    /// <summary>冷温水流量[L/min]</summary>
    public double WaterFlowRate { get; private set; }

    /// <summary>冷温水出口温度[C]</summary>
    public double WaterOutletTemperature { get; private set; }

    /// <summary>コイル処理熱量[kW]（冷却・加熱とも正値）</summary>
    public double CoilLoad { get; private set; }

    /// <summary>ファン消費電力[kW]（給気+還気）</summary>
    public double FanElectricity { get; private set; }

    /// <summary>ポンプ消費電力[kW]（定格水量時に定格能力/WTF。実際の熱交換量によらず水量に比例）</summary>
    public double PumpElectricity { get; private set; }

    /// <summary>加湿器作動状態</summary>
    public bool HumidifierOn { get; private set; }

    /// <summary>加湿器の水消費量[kg/s]</summary>
    public double HumidifierWaterConsumption { get; private set; }

    #endregion

    #region インスタンス変数

    private readonly CrossFinHeatExchanger cCoil;
    private readonly CrossFinHeatExchanger hCoil;
    private readonly Humidifier humidifier;
    private readonly RotaryRegenerator rGen;
    private readonly Regulator oaDamper;

    /// <summary>ファン設計消費電力[kW]（給気+還気。相似則で回転数比^3を乗じて使う）</summary>
    private readonly double designFanElectricity;

    /// <summary>外気枝の設計駆動差圧[kPa]（全開・バイパスなし・定格回転数で設計外気量となるよう校正）</summary>
    private readonly double oaDrivingPressure;

    #endregion

    #region コンストラクタ

    public AirHandlingUnitModel()
    {
      //コイル（Shizuku1定格。簡略コンストラクタ: 面風速2.5m/s、乾湿境界RH95%、管内流速2.5m/s）
      double saMass = DESIGN_SA_FLOW * 1.2 / 3600;
      double hrt = MoistAir.GetHumidityRatioFromDryBulbTemperatureAndWetBulbTemperature(26.6, 19.3, 101.325);
      cCoil = new CrossFinHeatExchanger(saMass, 2.5, 26.6, hrt, 95, DESIGN_CHW_FLOW / 60, 2.5, DESIGN_CHW_FLOW / 60, 7, DESIGN_COOLING_CAPACITY);
      hrt = MoistAir.GetHumidityRatioFromDryBulbTemperatureAndWetBulbTemperature(20.6, 14.2, 101.325);
      hCoil = new CrossFinHeatExchanger(saMass, 2.5, 20.6, hrt, 95, DESIGN_HW_FLOW / 60, 2.5, DESIGN_HW_FLOW / 60, 44, DESIGN_HEATING_CAPACITY);

      //全熱交換器（効率0.76、全熱型、消費電力0.1kW）と加湿器（滴下浸透気化式、飽和効率0.9、水利用率0.5）
      rGen = new RotaryRegenerator(0.76, true, 0.1);
      humidifier = new Humidifier(Humidifier.HumidifierType.WettedMedia, 0.9, 0.5);

      //ファン設計消費電力（定格静圧: 給気0.85kPa、還気0.65kPa）
      CentrifugalFan sFan = new CentrifugalFan(0.85, DESIGN_SA_FLOW / 3600d, 0.85, DESIGN_SA_FLOW / 3600d, 4, true);
      CentrifugalFan rFan = new CentrifugalFan(0.65, DESIGN_RA_FLOW / 3600d, 0.65, DESIGN_RA_FLOW / 3600d, 4, true);
      sFan.UpdateState(DESIGN_SA_FLOW / 3600d);
      rFan.UpdateState(DESIGN_RA_FLOW / 3600d);
      designFanElectricity = sFan.GetElectricConsumption() + rFan.GetElectricConsumption();

      //外気ダンパと外気枝の校正: 全開・バイパスなし・定格回転数で設計外気量となる駆動差圧を求める
      double qOADesign = DESIGN_OA_FLOW / 3600d;
      oaDamper = new Regulator(qOADesign, 0.02, DAMPER_RANGE_ABILITY, DAMPER_LINEAR_WEIGHT);
      oaDamper.IsTotallyClosable = true;
      oaDamper.Lift = 1.0;
      oaDrivingPressure = (OA_DUCT_RESISTANCE + HEX_RESISTANCE + oaDamper.GetResistance())
        * qOADesign * qOADesign;
    }

    #endregion

    #region 公開メソッド

    /// <summary>操作量と境界条件に基づいて空調機の状態を更新する</summary>
    /// <param name="roomTemperature">室温[C]（還気状態）</param>
    /// <param name="roomHumidityRatio">室絶対湿度[kg/kg]</param>
    /// <param name="outdoorTemperature">外気温度[C]</param>
    /// <param name="outdoorHumidityRatio">外気絶対湿度[kg/kg]</param>
    public void Update(double roomTemperature, double roomHumidityRatio,
      double outdoorTemperature, double outdoorHumidityRatio)
    {
      //弁アクチュエータ: 一定速度で指令開度へ移動（全ストロークVALVE_TRAVEL_TIME秒のレート制限）
      //空調機停止中も指令には追従する
      double travel = Settings.Instance.ValveTravelTime;
      double target = Math.Max(0, Math.Min(1, WaterValvePosition));
      if (travel <= 0) ActualValvePosition = target;
      else
      {
        double maxChange = TimeStep / travel;
        double change = target - ActualValvePosition;
        ActualValvePosition += Math.Abs(change) <= maxChange ? change : Math.Sign(change) * maxChange;
      }

      //弁開度→水量（イコールパーセント特性・定差圧・全閉可能）
      double designWater = (IsCoolingMode ? DESIGN_CHW_FLOW : DESIGN_HW_FLOW) / 60; //[kg/s]
      double minRate = 1 / VALVE_RANGE_ABILITY;
      double flowRate = (Math.Pow(VALVE_RANGE_ABILITY, ActualValvePosition - 1) - minRate) / (1 - minRate); //開度0で流量0に正規化
      double mWater = designWater * Math.Max(0, flowRate);
      WaterFlowRate = mWater * 60;

      //ポンプ電力: 定格水量時に定格能力/WTF、変流量時は流量比で減少（回転数制御相当）
      //熱交換量ではなく水量に比例するため、空調機停止中でも弁が開いていれば電力を消費する
      double designCapacity = IsCoolingMode ? DESIGN_COOLING_CAPACITY : DESIGN_HEATING_CAPACITY;
      PumpElectricity = designCapacity / Settings.Instance.PumpWTF * (mWater / designWater);

      double waterInTemp = IsCoolingMode ? ChilledWaterInletTemperature : HotWaterInletTemperature;

      //停止時（空気側のみ停止。水は弁開度なりに流れ続ける）
      if (!IsOn)
      {
        SupplyAirMassFlowRate = SupplyAirVolumetricFlowRate = OAVolumetricFlowRate = 0;
        CoilLoad = FanElectricity = HumidifierWaterConsumption = 0;
        WaterOutletTemperature = waterInTemp; //空気が流れず熱交換なし
        SupplyAirTemperature = roomTemperature;
        SupplyAirHumidityRatio = roomHumidityRatio;
        HumidifierOn = false;
        return;
      }

      //風量計算******************************************
      //給気: ファン相似則（風量∝回転数比）
      double rRatio = Math.Max(0.4, Math.Min(1.0, FanSpeedRatio));
      double qSA = DESIGN_SA_FLOW / 3600d * rRatio;
      double mSA = qSA * 1.2;
      SupplyAirVolumetricFlowRate = qSA;
      SupplyAirMassFlowRate = mSA;

      //外気: 駆動差圧∝回転数比^2、外気枝（ダクト+ダンパ+全熱交）の抵抗との平衡流量
      double qOA = 0;
      double dmpLift = Math.Max(0, Math.Min(1, OADamperPosition));
      if (1e-4 < dmpLift)
      {
        oaDamper.Lift = dmpLift;
        double pathResist = OA_DUCT_RESISTANCE + oaDamper.GetResistance() + (BypassHEX ? 0 : HEX_RESISTANCE);
        qOA = rRatio * Math.Sqrt(oaDrivingPressure / pathResist);
        qOA = Math.Min(qOA, qSA); //外気量は給気量を超えない
      }
      OAVolumetricFlowRate = qOA;
      double qRec = qSA - qOA;                       //再循環
      double qRA = DESIGN_RA_FLOW / 3600d * rRatio;  //還気（排気=還気-再循環）
      double qEA = Math.Max(0, qRA - qRec);

      //ファン消費電力（相似則: ∝回転数比^3）と還気ファン発熱**************
      double sFanElec = designFanElectricity * DESIGN_SA_FLOW / (DESIGN_SA_FLOW + DESIGN_RA_FLOW)
        * rRatio * rRatio * rRatio;
      double rFanElec = designFanElectricity * DESIGN_RA_FLOW / (DESIGN_SA_FLOW + DESIGN_RA_FLOW)
        * rRatio * rRatio * rRatio;
      FanElectricity = sFanElec + rFanElec;
      double cpAir = MoistAir.DryAirIsobaricSpecificHeat
        + MoistAir.VaporIsobaricSpecificHeat * roomHumidityRatio; //[kJ/(kg K)]
      double raTemp = roomTemperature + rFanElec / (qRA * 1.2 * cpAir);

      //全熱交換器****************************************
      double oaTemp = outdoorTemperature;
      double oaHumid = outdoorHumidityRatio;
      if (!BypassHEX && 1e-6 < qOA && 1e-6 < qEA)
      {
        rGen.UpdateState(qOA * 3600, qEA * 3600, 1.0, outdoorTemperature, outdoorHumidityRatio, raTemp, roomHumidityRatio);
        oaTemp = rGen.SupplyAirOutletDryBulbTemperature;
        oaHumid = rGen.SupplyAirOutletHumidityRatio;
      }

      //混合**********************************************
      double mixTemp = (qRec * raTemp + qOA * oaTemp) / qSA;
      double mixHumid = (qRec * roomHumidityRatio + qOA * oaHumid) / qSA;

      //給気ファン（押込形: コイル・加湿器の上流に位置し、ファン発熱は混合空気に加わる）
      mixTemp += sFanElec / (mSA * cpAir);

      //冷温水コイル**
      double coilOutTemp = mixTemp;
      double coilOutHumid = mixHumid;
      WaterOutletTemperature = waterInTemp;
      CoilLoad = 0;
      if (1e-6 < mWater)
      {
        CrossFinHeatExchanger coil = IsCoolingMode ? cCoil : hCoil;
        coil.UpdateOutletState(mixTemp, mixHumid, waterInTemp, mSA, mWater);
        coilOutTemp = coil.OutletAirTemperature;
        coilOutHumid = coil.OutletAirHumidityRatio;
        WaterOutletTemperature = coil.OutletWaterTemperature;
        CoilLoad = Math.Abs(mWater * 4.186 * (coil.OutletWaterTemperature - waterInTemp));
      }

      //加湿器（暖房時のみ、還気相対湿度によるOn/Off制御を内蔵）****
      double raRHumid = MoistAir.GetRelativeHumidityFromDryBulbTemperatureAndHumidityRatio(
        roomTemperature, roomHumidityRatio, PhysicsConstants.StandardAtmosphericPressure);
      if (!IsCoolingMode && HumidifierEnabled)
      {
        if (raRHumid < HumiditySetPoint - HumidityDeadband) HumidifierOn = true;
        else if (HumiditySetPoint + HumidityDeadband < raRHumid) HumidifierOn = false;
      }
      else HumidifierOn = false;
      HumidifierWaterConsumption = 0;
      if (HumidifierOn)
      {
        humidifier.UpdateOutletState(coilOutTemp, coilOutHumid, mSA);
        coilOutTemp = humidifier.OutletAirTemperature;
        coilOutHumid = humidifier.OutletAirHumidityRatio;
        HumidifierWaterConsumption = humidifier.WaterConsumption;
      }

      //給気状態を確定（押込形のためファン発熱は加算済み）**
      SupplyAirTemperature = coilOutTemp;
      SupplyAirHumidityRatio = coilOutHumid;
    }

    #endregion

  }
}

