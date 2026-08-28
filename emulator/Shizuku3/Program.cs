using System.Text;
using Popolo.Core.Building;
using Popolo.Core.Climate;

namespace Shizuku3
{
  /// <summary>熱負荷計算モデルの妥当性確認テスト</summary>
  internal class Program
  {

    static void Main(string[] args)
    {
      //既定はBACnetサーバ（本番モード）。引数testで開発用テストを実行
      if (args.Length == 0 || args[0] != "test")
      {
        RunServer();
        return;
      }

      RunNaturalTempTest();
      Console.WriteLine();
      RunHeatLoadTest();
      Console.WriteLine();
      RunAHUTest();
      Console.WriteLine();
      RunEmulatorTest(new DateTime(2026, 8, 5), 0.5);  //夏季代表日
      Console.WriteLine();
      RunEmulatorTest(new DateTime(2026, 1, 21), 0.5); //冬季代表日
      Console.WriteLine();
      RunTimeManagementTest();
    }

    #region 本番モード（BACnetサーバ）

    /// <summary>BACnetサーバとして起動する（Yabe等のクライアントから操作する本番モード）</summary>
    static void RunServer()
    {
      Console.WriteLine($"Starting Shizuku3 emulator (preconditioning)... " +
        $"start date {Settings.Instance.SimulationStartDate:yyyy/MM/dd}, time step {Settings.Instance.TimeStep} sec");
      EmulatorService svc = new EmulatorService();
      Shizuku3BACnetDevice device = new Shizuku3BACnetDevice(svc);
      svc.Start();
      Console.WriteLine($"BACnet server started: DeviceID={Settings.Instance.DeviceID}, " +
        $"Port={Settings.Instance.UdpPort}, Endpoint={Settings.Instance.LocalEndpoint}");
      Console.WriteLine($"Simulation time {svc.Emulator.CurrentDateTime:yyyy/MM/dd HH:mm}, " +
        $"acceleration {svc.AccelerationRate} (write AV301 to start), " +
        $"pause at {svc.PauseAtDateTime:yyyy/MM/dd HH:mm}. Press Enter to quit.");

      //シミュレーション1時間毎のサマリと1日毎のKPIを出力
      DateTime lastLogged = svc.Emulator.CurrentDateTime;
      DateTime lastKPIDate = svc.Emulator.CurrentDateTime.Date;
      double dayEnergy = 0, dayPPD = 0, dayOccPPD = 0, dayCO2Excess = 0; //日初のKPIスナップショット
      System.Timers.Timer logTimer = new System.Timers.Timer(500);
      logTimer.Elapsed += (o, e) =>
      {
        lock (svc.LockObj)
        {
          Shizuku3Emulator emu = svc.Emulator;
          if (emu.CurrentDateTime < lastLogged.AddHours(1)) return;
          lastLogged = emu.CurrentDateTime;
          Console.WriteLine($"{emu.CurrentDateTime:MM/dd HH:mm} Outdoor {emu.OutdoorTemperature,5:F1}C, " +
            $"Room {emu.Load.Zone.Temperature,5:F2}C, CO2 {emu.Load.CO2Level_PPM,5:F0}ppm, " +
            $"Occupants {emu.Load.StayWorkerCount,2}, SA {emu.AHU.SupplyAirTemperature,5:F2}C, " +
            $"Energy {emu.IntegratedEnergy_kWh,6:F1}kWh, Acc {svc.AccelerationRate}");

          //日付が変わったら前日分のKPI（積算の差分）を出力
          if (lastKPIDate < emu.CurrentDateTime.Date)
          {
            Console.WriteLine($"=== Daily KPI {lastKPIDate:yyyy/MM/dd}: " +
              $"Energy {emu.IntegratedEnergy_kWh - dayEnergy:F1} kWh, " +
              $"PPD {emu.IntegratedPPD - dayPPD:F0} %h, " +
              $"Occupant-weighted PPD {emu.IntegratedOccupantWeightedPPD - dayOccPPD:F0} person%h, " +
              $"CO2 excess {emu.CO2ExcessTime_h - dayCO2Excess:F2} h ===");
            lastKPIDate = emu.CurrentDateTime.Date;
            dayEnergy = emu.IntegratedEnergy_kWh;
            dayPPD = emu.IntegratedPPD;
            dayOccPPD = emu.IntegratedOccupantWeightedPPD;
            dayCO2Excess = emu.CO2ExcessTime_h;
          }
        }
      };
      logTimer.Start();

      Console.ReadLine();
      logTimer.Stop();
      svc.Stop();
    }

    #endregion

    #region テスト5: 時間管理（加速度・一時停止・リセット）

    /// <summary>時間管理の確認: 一時停止時刻での正確な自停止、KPIリセット、再開</summary>
    static void RunTimeManagementTest()
    {
      EmulatorService svc = new EmulatorService(); //setting.iniを読み込んで構築
      Console.WriteLine($"[テスト5] 時間管理: setting.ini読込 開始日時 {svc.Emulator.CurrentDateTime:yyyy/MM/dd}, " +
        $"助走 {svc.Emulator.PreconditionCycles}回");

      svc.AccelerationRate = 0;
      DateTime start = svc.Emulator.CurrentDateTime;
      DateTime pause1 = start.AddMinutes(30);
      svc.PauseAtDateTime = pause1;
      svc.Start();
      svc.AccelerationRate = 36000; //実時間0.05秒で30分進む

      bool stopped1 = waitForPause(svc, 15000);
      bool exact1 = svc.Emulator.CurrentDateTime == pause1;
      Console.WriteLine($"一時停止1: {svc.Emulator.CurrentDateTime:HH:mm:ss} " +
        $"(指定 {pause1:HH:mm:ss}) → {(stopped1 && exact1 ? "正確に自停止" : "NG")}");

      double energyBefore = svc.Emulator.IntegratedEnergy_kWh;
      svc.ResetKPI();
      bool kpiCleared = svc.Emulator.IntegratedEnergy_kWh == 0 && 0 < energyBefore;

      DateTime pause2 = pause1.AddMinutes(10);
      svc.PauseAtDateTime = pause2;
      svc.AccelerationRate = 36000;
      bool stopped2 = waitForPause(svc, 15000);
      bool exact2 = svc.Emulator.CurrentDateTime == pause2;
      Console.WriteLine($"一時停止2（再開後）: {svc.Emulator.CurrentDateTime:HH:mm:ss} " +
        $"(指定 {pause2:HH:mm:ss}) → {(stopped2 && exact2 ? "正確に自停止" : "NG")}, " +
        $"KPIリセット {(kpiCleared ? "OK" : "NG")}");
      svc.Stop();

      bool pass = stopped1 && exact1 && stopped2 && exact2 && kpiCleared;
      Console.WriteLine(pass ? "テスト5合格" : "テスト5不合格");
    }

    /// <summary>加速度が0になる（自停止する）まで待つ</summary>
    static bool waitForPause(EmulatorService svc, int timeoutMSec)
    {
      for (int i = 0; i < timeoutMSec / 10; i++)
      {
        if (svc.AccelerationRate == 0) return true;
        Thread.Sleep(10);
      }
      return false;
    }

    #endregion

    #region テスト4: 統合エミュレータ（気象・水温外乱・助走計算・KPI）

    /// <summary>統合エミュレータの1日運転確認（固定操作量による素朴な運転）</summary>
    static void RunEmulatorTest(DateTime startDate, double valvePosition)
    {
      const double TIME_STEP = 60;
      Shizuku3Emulator emu = new Shizuku3Emulator(TIME_STEP, startDate, 1, 2, 3);
      emu.AHU.WaterValvePosition = valvePosition;
      emu.AHU.FanSpeedRatio = 1.0;

      Console.WriteLine($"[テスト4] 統合エミュレータ {startDate:MM/dd}: 助走計算 {emu.PreconditionCycles}回で収束, " +
        $"初期室温（自然室温） {emu.Load.Zone.Temperature:F2}C");
      Console.WriteLine("時刻, 外気[C], 室温[C], 給気[C], CO2[ppm], 在室[人], PMV, 冷水温度[C]");
      double minT = double.MaxValue, maxT = double.MinValue, maxCO2 = 0, minChw = 99, maxChw = -99;
      while (emu.CurrentDateTime < startDate.AddDays(1))
      {
        emu.Step();
        IReadOnlyZone zn = emu.Load.Zone;
        minT = Math.Min(minT, zn.Temperature); maxT = Math.Max(maxT, zn.Temperature);
        maxCO2 = Math.Max(maxCO2, emu.Load.CO2Level_PPM);
        minChw = Math.Min(minChw, emu.ChilledWaterTemperature);
        maxChw = Math.Max(maxChw, emu.ChilledWaterTemperature);
        if (emu.CurrentDateTime.Minute == 0 && emu.CurrentDateTime.Hour % 3 == 0)
          Console.WriteLine($"{emu.CurrentDateTime:HH:mm}, {emu.OutdoorTemperature:F1}, {zn.Temperature:F2}, " +
            $"{emu.AHU.SupplyAirTemperature:F2}, {emu.Load.CO2Level_PPM:F0}, {emu.Load.StayWorkerCount}, " +
            $"{emu.PMV:F2}, {emu.ChilledWaterTemperature:F2}");
      }
      Console.WriteLine($"KPI: エネルギー {emu.IntegratedEnergy_kWh:F1}kWh, PPD積算 {emu.IntegratedPPD:F0}%h, " +
        $"人数重みPPD積算 {emu.IntegratedOccupantWeightedPPD:F0}人%h, CO2超過 {emu.CO2ExcessTime_h:F2}h");
      bool pass =
        emu.PreconditionCycles < 50 &&
        5 < minT && maxT < 45 &&              //室温が物理的な範囲
        500 < maxCO2 && maxCO2 < 3000 &&      //外気導入下で妥当なCO2ピーク
        4.0 < minChw && maxChw < 10.5 &&      //AR(1)水温が妥当な範囲で変動
        0 < emu.IntegratedEnergy_kWh && 0 < emu.IntegratedPPD;
      Console.WriteLine(pass ? "テスト4合格" : "テスト4不合格");
    }

    #endregion

    #region テスト1: 自然室温の収束確認

    /// <summary>自然室温の妥当性確認</summary>
    /// <remarks>
    /// 外気温湿度を固定、日射0、夜間放射0、内部発熱0、給気0kg/sとし、
    /// 室温・室絶対湿度が漏気と貫流のみで外気状態に漸近収束することを確認する。
    /// 湿度は壁体の湿気移動を計算しないため漏気のみで収束する（時定数約3日）。
    /// </remarks>
    static void RunNaturalTempTest()
    {
      const double OUTDOOR_TEMP = 30.0;
      const double OUTDOOR_HUMID = 0.018;
      const double TIME_STEP = 60;
      const int CALC_DAYS = 30;

      BuildingThermalModel bModel = BuildingModelBuilder.Make(TIME_STEP);
      IReadOnlyZone zone = bModel.MultiRoom[0].Zones[0];
      bModel.InitializeAirState(20, 0.005); //外気と大きく乖離した初期状態

      Sun sun = new Sun(Sun.City.Tokyo);
      DateTime dTime = new DateTime(2026, 8, 5, 0, 0, 0);
      DateTime endTime = dTime.AddDays(CALC_DAYS);

      Console.WriteLine($"[テスト1] 自然室温収束: 外気 {OUTDOOR_TEMP}C / {1000 * OUTDOOR_HUMID}g/kg 固定, " +
        "日射0, 内部発熱0, 給気0kg/s, 初期 20C / 5g/kg");

      double lastT = zone.Temperature;
      double lastW = zone.HumidityRatio;
      bool monotonicT = true, monotonicW = true;
      while (dTime < endTime)
      {
        sun.Update(dTime);
        sun.SetGlobalHorizontalRadiation(0, 0);
        bModel.UpdateOutdoorCondition(dTime, sun, OUTDOOR_TEMP, OUTDOOR_HUMID, 0);
        bModel.ControlHeatSupply(0, 0, 0);
        bModel.ControlMoistureSupply(0, 0, 0);
        bModel.ForecastHeatTransfer();
        bModel.ForecastWaterTransfer();
        bModel.FixState();
        dTime = dTime.AddSeconds(TIME_STEP);

        if (zone.Temperature < lastT - 1e-9) monotonicT = false;
        if (zone.HumidityRatio < lastW - 1e-12) monotonicW = false;
        lastT = zone.Temperature;
        lastW = zone.HumidityRatio;
      }

      double dT = Math.Abs(zone.Temperature - OUTDOOR_TEMP);
      double dW = Math.Abs(zone.HumidityRatio - OUTDOOR_HUMID);
      Console.WriteLine($"最終偏差: 温度 {dT:E3} K, 絶対湿度 {1000 * dW:E3} g/kg / " +
        $"単調収束: 温度 {(monotonicT ? "OK" : "NG")}, 湿度 {(monotonicW ? "OK" : "NG")}");
      bool pass = dT < 0.05 && dW < 0.0001 && monotonicT && monotonicW;
      Console.WriteLine(pass ? "テスト1合格: 外気に漸近収束" : "テスト1不合格");
    }

    #endregion

    #region テスト2: 内部発熱・執務者・CO2の確認

    /// <summary>熱負荷計算モデル（執務者・内部発熱・CO2）の妥当性確認</summary>
    /// <remarks>
    /// 外気固定・日射0の条件で1週間（水曜開始、土日を含む）を計算し、以下を確認する。
    /// (1) 在室: 平日日中に在室、深夜0人、休日は平日より大幅に少ない
    /// (2) CO2: 外気濃度未満にならない、在室時に上昇する
    /// (3) CO2収支: 同一の後退Euler式による参照計算と一致（配管・単位系の確認）
    /// (4) 内部発熱による室温上昇: 外気温を上回る
    /// </remarks>
    static void RunHeatLoadTest()
    {
      const double OUTDOOR_TEMP = 25.0;
      const double OUTDOOR_HUMID = 0.010;
      const double TIME_STEP = 60;
      const int CALC_DAYS = 7;
      const uint OCCUPANT_SEED = 2;

      HeatLoadModel model = new HeatLoadModel(TIME_STEP, OCCUPANT_SEED);
      IReadOnlyZone zone = model.Zone;

      Console.WriteLine($"[テスト2] 内部発熱・執務者・CO2: 外気 {OUTDOOR_TEMP}C 固定, 日射0, " +
        $"執務者数 {model.Tenant.OfficeWorkerCount}人（床面積{BuildingModelBuilder.FLOOR_AREA}m2から確率生成）");

      Sun sun = new Sun(Sun.City.Tokyo);
      DateTime dTime = new DateTime(2026, 8, 5, 0, 0, 0); //水曜開始
      DateTime endTime = dTime.AddDays(CALC_DAYS);

      using StreamWriter sWriter = new StreamWriter(
        Path.Combine(AppContext.BaseDirectory, "heatLoadTest.csv"), false, new UTF8Encoding(true));
      sWriter.WriteLine("日時,在室人数[人],乾球温度[C],絶対湿度[g/kg],CO2濃度[ppm],顕熱内部発熱[W]");

      //CO2参照計算（モデルと同一の後退Euler式を独立に解く）
      double co2Ref = HeatLoadModel.OUTDOOR_CO2_PPM * 1e-6;
      double co2Volume = zone.AirMass / Popolo.Core.Physics.PhysicsConstants.NominalMoistAirDensity;
      double maxCO2RefError = 0;

      //集計: [平日/休日]×[深夜2時/日中10-16時] の在室人数
      double wdayDaySum = 0, wdayNightSum = 0, holDaySum = 0;
      int wdayDayCnt = 0, wdayNightCnt = 0, holDayCnt = 0;
      double maxCO2 = 0, minCO2 = double.MaxValue, maxTemp = 0;

      int step = 0;
      while (dTime < endTime)
      {
        sun.Update(dTime);
        sun.SetGlobalHorizontalRadiation(0, 0);
        model.Building.UpdateOutdoorCondition(dTime, sun, OUTDOOR_TEMP, OUTDOOR_HUMID, 0);

        model.Update(dTime);

        model.Building.ForecastHeatTransfer();
        model.Building.ForecastWaterTransfer();
        model.Building.FixState();
        model.UpdateCO2();

        //CO2参照計算: (V/dt)(C'-C) = qA(Cout-C') + G の後退Euler解
        double qA = Math.Max(0, zone.VentilationRate) / Popolo.Core.Physics.PhysicsConstants.NominalMoistAirDensity;
        double gen = Popolo.Core.Building.AirQuality.CO2Balance.StandardCO2GenerationRatePerPerson * model.StayWorkerCount;
        co2Ref = (co2Volume / TIME_STEP * co2Ref + qA * HeatLoadModel.OUTDOOR_CO2_PPM * 1e-6 + gen)
          / (co2Volume / TIME_STEP + qA);
        maxCO2RefError = Math.Max(maxCO2RefError, Math.Abs(1e6 * co2Ref - model.CO2Level_PPM));

        //集計
        bool isHoliday = model.Tenant.IsHoliday(dTime);
        if (!isHoliday && dTime.Hour == 2) { wdayNightSum += model.StayWorkerCount; wdayNightCnt++; }
        if (!isHoliday && 10 <= dTime.Hour && dTime.Hour < 16) { wdayDaySum += model.StayWorkerCount; wdayDayCnt++; }
        if (isHoliday && 10 <= dTime.Hour && dTime.Hour < 16) { holDaySum += model.StayWorkerCount; holDayCnt++; }
        maxCO2 = Math.Max(maxCO2, model.CO2Level_PPM);
        minCO2 = Math.Min(minCO2, model.CO2Level_PPM);
        maxTemp = Math.Max(maxTemp, zone.Temperature);

        step++;
        dTime = dTime.AddSeconds(TIME_STEP);

        //10分毎にCSV書き出し
        if (step % 10 == 0)
          sWriter.WriteLine($"{dTime:yyyy/MM/dd HH:mm:ss},{model.StayWorkerCount}," +
            $"{zone.Temperature:F2},{1000 * zone.HumidityRatio:F2},{model.CO2Level_PPM:F0},{model.SensibleHeatGain:F0}");

        //1日毎にサマリ表示
        if (step % (24 * 60) == 0)
          Console.WriteLine($"{dTime.AddDays(-1):MM/dd(ddd)} 終了時点: 室温 {zone.Temperature:F2}C, " +
            $"CO2 {model.CO2Level_PPM:F0}ppm");
      }

      double wdayDayAve = wdayDaySum / wdayDayCnt;
      double wdayNightAve = wdayNightSum / wdayNightCnt;
      double holDayAve = holDaySum / holDayCnt;
      Console.WriteLine($"在室人数平均: 平日日中 {wdayDayAve:F1}人, 平日深夜 {wdayNightAve:F2}人, 休日日中 {holDayAve:F2}人");
      Console.WriteLine($"CO2濃度: 最小 {minCO2:F0}ppm, 最大 {maxCO2:F0}ppm / 参照計算との最大差 {maxCO2RefError:E2}ppm");
      Console.WriteLine($"最高室温: {maxTemp:F2}C（外気 {OUTDOOR_TEMP}C）");

      bool pass =
        0 < wdayDayAve &&                                //平日日中に在室
        wdayNightAve < 0.5 &&                            //平日深夜はほぼ無人
        holDayAve < 0.5 * wdayDayAve &&                  //休日は平日より大幅に少ない
        HeatLoadModel.OUTDOOR_CO2_PPM - 1 <= minCO2 &&   //外気濃度未満にならない
        HeatLoadModel.OUTDOOR_CO2_PPM + 100 < maxCO2 &&  //在室によりCO2が上昇する
        maxCO2RefError < 1.0 &&                          //CO2収支が参照計算と一致
        OUTDOOR_TEMP < maxTemp;                          //内部発熱で室温が外気を上回る
      Console.WriteLine(pass ? "テスト2合格" : "テスト2不合格");
    }

    #endregion

    #region テスト3: 空調機モデルの静特性確認

    /// <summary>空調機モデルの静特性確認</summary>
    /// <remarks>
    /// (1) 定格条件（ファン全速・ダンパ全開）で設計風量・設計外気量が再現される
    /// (2) 弁開度に対して給気温度が単調に低下（冷房）・上昇（暖房）する
    /// (3) ファン回転数比に比例して風量が変化し、消費電力は3乗で減少する
    /// (4) 外気ダンパ開度で外気量が変化し、全熱交バイパスで外気量が増える
    /// (5) 暖房時に加湿器がOn/Off制御される
    /// </remarks>
    static void RunAHUTest()
    {
      const double ROOM_T = 26, ROOM_W = 0.0105;
      const double OUT_T = 33, OUT_W = 0.018;

      AirHandlingUnitModel ahu = new AirHandlingUnitModel();
      Console.WriteLine("[テスト3] 空調機モデル静特性");

      //(1)(2) 冷房・弁開度スイープ
      ahu.IsCoolingMode = true;
      ahu.FanSpeedRatio = 1.0;
      ahu.OADamperPosition = 1.0;
      Console.WriteLine("弁開度, 給気温度[C], 水量[L/min], コイル熱量[kW], 給気風量[CMH], 外気量[CMH]");
      double lastSATemp = double.MaxValue;
      bool monotonic = true;
      double qSADesign = 0, qOADesign = 0, saTempAtValve0 = 0;
      foreach (double vlv in new double[] { 0, 0.25, 0.5, 0.75, 1.0 })
      {
        ahu.WaterValvePosition = vlv;
        ahu.Update(ROOM_T, ROOM_W, OUT_T, OUT_W);
        Console.WriteLine($"{vlv:F2}, {ahu.SupplyAirTemperature:F2}, {ahu.WaterFlowRate:F1}, " +
          $"{ahu.CoilLoad:F1}, {3600 * ahu.SupplyAirVolumetricFlowRate:F0}, {3600 * ahu.OAVolumetricFlowRate:F0}");
        if (lastSATemp <= ahu.SupplyAirTemperature) monotonic = false;
        lastSATemp = ahu.SupplyAirTemperature;
        if (vlv == 0) saTempAtValve0 = ahu.SupplyAirTemperature;
        qSADesign = 3600 * ahu.SupplyAirVolumetricFlowRate;
        qOADesign = 3600 * ahu.OAVolumetricFlowRate;
      }
      bool designFlowOK = Math.Abs(qSADesign - AirHandlingUnitModel.DESIGN_SA_FLOW) < 30 &&
        Math.Abs(qOADesign - AirHandlingUnitModel.DESIGN_OA_FLOW) < 30;

      //(3) ファン回転数比スイープ
      ahu.WaterValvePosition = 0.5;
      double elecAtFull = 0, elecAtMin = 0, qSAAtMin = 0;
      foreach (double rr in new double[] { 1.0, 0.7, 0.4 })
      {
        ahu.FanSpeedRatio = rr;
        ahu.Update(ROOM_T, ROOM_W, OUT_T, OUT_W);
        Console.WriteLine($"回転数比 {rr:F1}: 給気 {3600 * ahu.SupplyAirVolumetricFlowRate:F0}CMH, " +
          $"外気 {3600 * ahu.OAVolumetricFlowRate:F0}CMH, ファン電力 {ahu.FanElectricity:F2}kW, 給気温度 {ahu.SupplyAirTemperature:F2}C");
        if (rr == 1.0) elecAtFull = ahu.FanElectricity;
        if (rr == 0.4) { elecAtMin = ahu.FanElectricity; qSAAtMin = 3600 * ahu.SupplyAirVolumetricFlowRate; }
      }
      bool fanLawOK = Math.Abs(qSAAtMin - 0.4 * AirHandlingUnitModel.DESIGN_SA_FLOW) < 30 &&
        Math.Abs(elecAtMin / elecAtFull - 0.064) < 0.01; //0.4^3=0.064

      //(4) 外気ダンパスイープとバイパス
      ahu.FanSpeedRatio = 1.0;
      double qOAHalf = 0, qOAClosed = 0, qOABypass = 0;
      foreach (double dmp in new double[] { 1.0, 0.5, 0 })
      {
        ahu.OADamperPosition = dmp;
        ahu.Update(ROOM_T, ROOM_W, OUT_T, OUT_W);
        Console.WriteLine($"外気ダンパ {dmp:F1}: 外気 {3600 * ahu.OAVolumetricFlowRate:F0}CMH");
        if (dmp == 0.5) qOAHalf = 3600 * ahu.OAVolumetricFlowRate;
        if (dmp == 0) qOAClosed = 3600 * ahu.OAVolumetricFlowRate;
      }
      ahu.OADamperPosition = 1.0;
      ahu.BypassHEX = true;
      ahu.Update(ROOM_T, ROOM_W, OUT_T, OUT_W);
      qOABypass = 3600 * ahu.OAVolumetricFlowRate;
      Console.WriteLine($"バイパス時: 外気 {qOABypass:F0}CMH");
      ahu.BypassHEX = false;
      bool damperOK = qOAClosed == 0 && 0 < qOAHalf && qOAHalf < qOADesign && qOADesign < qOABypass;

      //(5) 暖房・加湿
      ahu.IsCoolingMode = false;
      ahu.WaterValvePosition = 1.0;
      ahu.Update(20, 0.008, 5, 0.003); //還気RH約55% → 加湿Off、純加熱
      bool heatingOK = 20 < ahu.SupplyAirTemperature && !ahu.HumidifierOn;
      Console.WriteLine($"暖房・高湿時: 給気 {ahu.SupplyAirTemperature:F2}C, 加湿 {(ahu.HumidifierOn ? "On" : "Off")}（純加熱で給気>還気を確認）");
      ahu.Update(20, 0.004, 5, 0.003); //還気RH約27% → 加湿On
      //気化式（断熱加湿）のため加湿中の給気温度は低下するのが正しい。湿度の増加を確認する
      bool humidOnOK = ahu.HumidifierOn && 0.005 < ahu.SupplyAirHumidityRatio;
      Console.WriteLine($"暖房・低湿時: 給気 {ahu.SupplyAirTemperature:F2}C / {1000 * ahu.SupplyAirHumidityRatio:F2}g/kg, " +
        $"加湿 {(ahu.HumidifierOn ? "On" : "Off")}（気化式のため断熱冷却を伴う）");

      Console.WriteLine($"設計風量再現 {(designFlowOK ? "OK" : "NG")}, 弁-給気温度単調性 {(monotonic ? "OK" : "NG")}, " +
        $"ファン相似則 {(fanLawOK ? "OK" : "NG")}, ダンパ・バイパス {(damperOK ? "OK" : "NG")}, " +
        $"暖房・加湿 {(heatingOK && humidOnOK ? "OK" : "NG")}");
      bool pass = designFlowOK && monotonic && fanLawOK && damperOK && heatingOK && humidOnOK;
      Console.WriteLine(pass ? "テスト3合格" : "テスト3不合格");
    }

    #endregion

  }
}
