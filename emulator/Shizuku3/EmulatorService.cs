using System.Diagnostics;

namespace Shizuku3
{
  /// <summary>エミュレータの時間管理（加速度・一時停止時刻・リセット）を担うサービス</summary>
  /// <remarks>
  /// ・AccelerationRate: 実時間1秒あたりに進めるシミュレーション秒数。0で停止
  /// ・PauseAtDateTime: この時刻に達した時点で正確に自停止（加速度を0にする）。
  /// 　制御→指定時間進行→停止のステップ実行の基盤（Shizuku2と同方式）
  /// ・Reset: setting.iniを再読込してエミュレータを再構築（BACnetのReinitializeDevice COLDSTART相当）
  /// ・ResetKPI: KPI積算のみクリア（WARMSTART相当）
  /// 状態の読み書きはLockObjを介して行う（将来のBACnet層との排他）
  /// </remarks>
  public class EmulatorService
  {

    #region プロパティ・インスタンス変数

    /// <summary>エミュレータ本体</summary>
    public Shizuku3Emulator Emulator { get; private set; }

    /// <summary>加速度（実時間1秒あたりのシミュレーション秒数。0=停止）</summary>
    public uint AccelerationRate { get; set; }

    /// <summary>一時停止時刻（この時刻に達すると加速度が0になる）</summary>
    public DateTime? PauseAtDateTime { get; set; }

    /// <summary>状態読み書きの排他用オブジェクト</summary>
    public object LockObj { get; } = new object();

    private Thread? loopThread;
    private volatile bool running;

    #endregion

    #region コンストラクタ・公開メソッド

    /// <summary>一時停止時刻の既定オフセット[sec]（1日課題では到達しない=途中停止しない値）</summary>
    public const double DEFAULT_PAUSE_OFFSET = 87600;

    public EmulatorService()
    {
      Emulator = CreateEmulator();
      AccelerationRate = Settings.Instance.AccelerationRate;
      PauseAtDateTime = Emulator.CurrentDateTime.AddSeconds(DEFAULT_PAUSE_OFFSET);
    }

    /// <summary>時間進行ループを開始する</summary>
    public void Start()
    {
      if (running) return;
      running = true;
      loopThread = new Thread(runLoop) { IsBackground = true };
      loopThread.Start();
    }

    /// <summary>時間進行ループを終了する</summary>
    public void Stop()
    {
      running = false;
      loopThread?.Join(1000);
    }

    /// <summary>setting.iniを再読込してエミュレータを初期状態に戻す（COLDSTART相当）</summary>
    public void Reset()
    {
      lock (LockObj)
      {
        Settings.Reload();
        Emulator = CreateEmulator();
        AccelerationRate = Settings.Instance.AccelerationRate;
        PauseAtDateTime = Emulator.CurrentDateTime.AddSeconds(DEFAULT_PAUSE_OFFSET);
      }
    }

    /// <summary>KPI積算のみクリアする（WARMSTART相当）</summary>
    public void ResetKPI()
    {
      lock (LockObj) Emulator.ClearKPI();
    }

    private static Shizuku3Emulator CreateEmulator()
    {
      Settings s = Settings.Instance;
      return new Shizuku3Emulator(s.TimeStep, s.SimulationStartDate,
        s.WeatherSeed, s.OccupantSeed, s.WaterTempSeed);
    }

    #endregion

    #region 時間進行ループ

    private void runLoop()
    {
      Stopwatch sWatch = Stopwatch.StartNew();
      double owedSimSeconds = 0; //未消化のシミュレーション秒数
      double timeStep = Settings.Instance.TimeStep;

      while (running)
      {
        uint acc = AccelerationRate;
        if (acc == 0)
        {
          owedSimSeconds = 0;
          sWatch.Restart();
          Thread.Sleep(20);
          continue;
        }

        owedSimSeconds += sWatch.Elapsed.TotalSeconds * acc;
        sWatch.Restart();
        //計算が追いつかない場合の暴走防止（未消化分は最大10ステップまで持ち越す）
        owedSimSeconds = Math.Min(owedSimSeconds, 10 * timeStep);

        while (running && timeStep <= owedSimSeconds && AccelerationRate != 0)
        {
          lock (LockObj)
          {
            if (checkPause()) break;
            Emulator.Step();
            owedSimSeconds -= timeStep;
            if (checkPause()) break;
          }
        }
        Thread.Sleep(2);
      }
    }

    /// <summary>一時停止時刻に達していれば停止する</summary>
    private bool checkPause()
    {
      if (PauseAtDateTime.HasValue && PauseAtDateTime.Value <= Emulator.CurrentDateTime)
      {
        AccelerationRate = 0;
        return true;
      }
      return false;
    }

    #endregion

  }
}
