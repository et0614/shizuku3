using Popolo.Core.Building;
using Popolo.Core.Building.Envelope;
using Popolo.Core.Climate;

namespace Shizuku3
{
  /// <summary>Shizuku3の建物熱モデル（Shizuku1基準階南側ペリメータ、単一ゾーン）を作成する</summary>
  /// <remarks>
  /// 仕様は docs「01_物理モデル諸元.md」に従う。
  /// ・ゾーン: SWP+SP1-SP4統合（176.5m2、天井高2.7m）、瞬時完全混合
  /// ・外皮: 南・西面のみ外気暴露。梁部面積は外壁一般部に吸収。ブラインドなし
  /// ・北・東面: 断熱内壁（隣接空間温度=室温、AdjacentSpaceFactor=0）
  /// ・床・天井: 床スラブ両面を同一ゾーンに面するループ壁とし、縦方向無限繰り返しを表現
  /// ・給気は0kg/sのまま（空調機モデル実装後に接続する）
  /// </remarks>
  public static class BuildingModelBuilder
  {

    #region 定数（形状: Shizuku1 Building.cs原典より転記）

    /// <summary>床面積[m2]（SWP:45.5 + SP1:39.0 + SP2:26.0 + SP3:40.0 + SP4:26.0）</summary>
    public const double FLOOR_AREA = 176.5;

    /// <summary>天井高[m]</summary>
    public const double CEILING_HEIGHT = 2.7;

    /// <summary>西外壁面積[m2]（一般部32.76 + 梁部12.60）</summary>
    public const double WALL_AREA_W = 45.36;

    /// <summary>南外壁面積[m2]（一般部 7.42+22.25+14.83+20.36+12.17 + 梁部 2.93+8.78+5.85+9.00+5.85）</summary>
    public const double WALL_AREA_S = 109.44;

    /// <summary>断熱内壁面積[m2]（北側32.75m + SWP東側10m + SWP北側3.25m + SP4東側4m）×2.7m</summary>
    public const double WALL_AREA_IN = 135.0;

    /// <summary>南窓面積[m2]（5.32×(0.5+1.5+1.0+2.0+1.0)）</summary>
    public const double WINDOW_AREA_S = 31.92;

    /// <summary>西窓面積[m2]（5.32×2.0）</summary>
    public const double WINDOW_AREA_W = 10.64;

    /// <summary>ガラスの日射透過率[-]</summary>
    private const double GLASS_TRANSMITTANCE = 0.815;

    /// <summary>ガラスの日射反射率[-]</summary>
    private const double GLASS_REFLECTANCE = 0.072;

    /// <summary>漏気回数[回/h]（換気回数法）</summary>
    private const double INFILTRATION_ACH = 0.1;

    #endregion

    #region 公開メソッド

    /// <summary>建物熱モデルを作成する</summary>
    /// <param name="timeStep">計算時間刻み[sec]</param>
    public static BuildingThermalModel Make(double timeStep)
    {
      //傾斜面
      Incline incS = new Incline(Incline.Orientation.S, 0.5 * Math.PI);
      Incline incW = new Incline(Incline.Orientation.W, 0.5 * Math.PI);

      //壁層構成（Shizuku1転記。物性は(名称, 熱伝導率W/mK, 容積比熱kJ/m3K, 厚みm)）
      WallLayer[] exWl = new WallLayer[]
      {
        new WallLayer("タイル", 1.3, 2000, 0.010),
        new WallLayer("セメント・モルタル", 1.5, 1600, 0.025),
        new WallLayer("コンクリート", 1.6, 2000, 0.150),
        new WallLayer("押出ポリスチレンフォーム1種", 0.040, 33, 0.025),
        new WallLayer(WallLayer.Material.AirGap, 0.05),
        new WallLayer("石膏ボード", 0.22, 830, 0.008),
      };
      WallLayer[] flWl = new WallLayer[]
      {
        new WallLayer("ビニル系床材", 0.190, 2000, 0.003),
        new WallLayer(WallLayer.Material.AirGap, 0.05),
        new WallLayer("コンクリート", 1.6, 2000, 0.150),
        new WallLayer(WallLayer.Material.AirGap, 0.05),
        new WallLayer("石膏ボード", 0.220, 830, 0.009),
        new WallLayer("ロックウール化粧吸音板", 0.064, 290, 0.015),
      };
      WallLayer[] inWl = new WallLayer[]
      {
        new WallLayer("石膏ボード", 0.220, 830, 0.012),
        new WallLayer(WallLayer.Material.AirGap, 0.05),
        new WallLayer("石膏ボード", 0.220, 830, 0.012),
      };

      //壁
      Wall wallW = new Wall(WALL_AREA_W, exWl);   //西外壁
      Wall wallS = new Wall(WALL_AREA_S, exWl);   //南外壁
      Wall wallIn = new Wall(WALL_AREA_IN, inWl); //断熱内壁（北・東）
      Wall wallFl = new Wall(FLOOR_AREA, flWl);   //床スラブ（ループ壁: F=床表面, B=天井表面）
      Wall[] walls = new Wall[] { wallW, wallS, wallIn, wallFl };
      foreach (Wall wl in walls)
      {
        wl.ShortWaveAbsorptanceF = wl.ShortWaveAbsorptanceB = 0.8;
        wl.LongWaveEmissivityF = wl.LongWaveEmissivityB = 0.9;
        wl.RadiativeCoefficientF = wl.RadiativeCoefficientB = 5;
        wl.ConvectiveCoefficientF = wl.ConvectiveCoefficientB = 4;
      }
      //外壁の屋外側（F側、第1層タイル）のみ対流熱伝達率18
      wallW.ConvectiveCoefficientF = 18;
      wallS.ConvectiveCoefficientF = 18;

      //窓（ブラインドなし）
      Window winS = new Window(WINDOW_AREA_S,
        new double[] { GLASS_TRANSMITTANCE }, new double[] { GLASS_REFLECTANCE }, incS);
      Window winW = new Window(WINDOW_AREA_W,
        new double[] { GLASS_TRANSMITTANCE }, new double[] { GLASS_REFLECTANCE }, incW);
      foreach (Window wn in new Window[] { winS, winW })
      {
        wn.ConvectiveCoefficientF = 18;
        wn.ConvectiveCoefficientB = 4;
        wn.LongWaveEmissivityF = wn.LongWaveEmissivityB = 0.9;
      }

      //ゾーン（気積の空気質量換算はShizuku1同様1.2倍係数）
      Zone zone = new Zone("南側ペリメータ", FLOOR_AREA * CEILING_HEIGHT * 1.2, FLOOR_AREA);
      zone.HeatCapacity = zone.AirMass * 1006 * 10; //家具等熱容量
      zone.VentilationRate = INFILTRATION_ACH * zone.AirMass / 3600; //漏気（換気回数法）
      zone.ControlHeatSupply(0);
      zone.ControlMoistureSupply(0);

      //多数室
      MultiRoom mRoom = new MultiRoom(1, new Zone[] { zone }, walls, new Window[] { winS, winW });
      mRoom.AddZone(0, 0);
      mRoom.SetOutsideEnvelope(wallW, true, incW); mRoom.AddWall(zone, wallW, false);
      mRoom.SetOutsideEnvelope(wallS, true, incS); mRoom.AddWall(zone, wallS, false);
      mRoom.SetAdjacentSpaceFactor(wallIn, true, 0.0); mRoom.AddWall(zone, wallIn, false); //断熱境界（隣接温度=室温）
      mRoom.AddLoopWall(zone, wallFl); //床・天井: 縦方向無限繰り返し
      mRoom.AddWindow(zone, winS);
      mRoom.AddWindow(zone, winW);

      //建物モデル
      BuildingThermalModel bModel = new BuildingThermalModel(new MultiRoom[] { mRoom });
      bModel.TimeStep = timeStep;
      bModel.InitializeAirState(22, 0.0105); //ゾーン・壁体の状態初期化（モデル構成完了後に呼ぶ必要がある）
      bModel.SetSupplyAir(0, 0, 22, 0.0105, 0); //給気0kg/s（空調機モデル接続までのプレースホルダ）

      return bModel;
    }

    #endregion

  }
}
