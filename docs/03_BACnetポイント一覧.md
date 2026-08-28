# Shizuku3 BACnetポイント一覧

作成日: 2026-08-28(最終更新: 同日) / 状態: 仕様検討版

## 1. 実装方針

- ライブラリ: **BACnet 4.0.0(NuGet、System.IO.BACnet)**。実装パターンは
  **PoEMServer**(`C:\git_repositories\poem\software\PoEMServer`)を踏襲する
  (DeviceStorage+拡張AddObject、COVイベント、サービス宣言等。
  Shizuku1/2のBACnet実装は踏襲しない)
- ポイント仕様は一般的なBACnetの慣習に従う:
  - **AI(Analog Input)** = センサ計測値(読取専用)
  - **AO(Analog Output)/BO(Binary Output)** = 現場機器への操作出力(書込可・**commandable**)
  - **MSV(Multi-State Value)** = モード類(状態は1始まりの列挙)
  - commandableオブジェクトは **Priority_Array(16段)+Relinquish_Default** を持つ。
    Relinquish_Defaultに標準値(§3の既定値)を設定し、全priorityがNULLなら標準値に戻る
    (=「学生が触らなければ標準状態で機能する」ことのBACnet的表現)。
    学生・ラッパーの書込みは慣習どおりpriority 16を既定とする
  - 全オブジェクトに **Object_Name(英語ASCII)・Description(日本語可)・
    Engineering Units** を設定。AIには **COV_Increment** を設定しCOV通知に対応
  - Status_Flags / Reliability / Out_Of_Service を実装(PoEMServerパターン)
- デバイスは1台のみ。DEVICE_ID・ポートはsetting.ini
- サービス: WhoIs/IAm、ReadProperty(Multiple)、WriteProperty、SubscribeCOV、
  **ReinitializeDevice**(§5)。TimeSynchronizationは**受理しない**
  (シミュレーション時刻は外部から同期されるべきものではないため)
- インスタンス番号は用途別に百番台で区分(操作量=100番台、計測量=200番台、
  KPI=230番台、シミュレーション管理=300番台)

## 2. シミュレーション時刻の公開

BACnetの慣習に従い、**Deviceオブジェクトの Local_Date / Local_Time プロパティ**で
現在のシミュレーション時刻を公開する(実時刻ではなくシミュレーション内時刻を返す)。
補助として読取専用のDateTime Valueオブジェクト(§5)も併設する。

## 3. 操作量(commandable)

| Inst. | Object_Name | 型 | 範囲 | Relinquish_Default | Units | 説明 |
|---|---|---|---|---|---|---|
| 101 | WaterValvePosition | AO | 0–1 | 0 | percent(0–1無次元でも可、実装時に統一) | 冷温水二方弁開度。冷暖モードに応じ冷水/温水弁として作用 |
| 102 | FanSpeedRatio | AO | 0.4–1.0 | 1.0 | no-units | ファン回転数比(給気・還気連動)。AHU停止中は無効 |
| 103 | OADamperPosition | AO | 0–1 | 1.0 | no-units | 外気ダンパ開度(還気ダンパ連動)。既定=全開(設計外気量) |
| 104 | AHUOnOff | BO | inactive/active | active | - | AHU発停。発停スケジュール管理自体を学習課題とするため既定は運転 |
| 105 | OperationMode | MSV | 1=Auto / 2=Cooling / 3=Heating | 1 | - | 冷暖モード。Auto=カレンダーによる自動切替 |
| 106 | HEXBypass | BO | inactive/active | inactive | - | 全熱交換器バイパス(inactive=熱回収有効)。発展課題用 |
| 107 | HumidifierEnabled | BO | inactive/active | active | - | 加湿器の有効/無効(On/Off制御自体は本体内蔵) |
| 108 | HumiditySetPoint | AO | %RH | 40 | percent-relative-humidity | 加湿On/Off制御の設定湿度 |
| 109 | HumidityDeadband | AO | %RH | 10 | percent-relative-humidity | 同ディファレンシャル(設定±幅でOn/Off) |

初学者が触るのは101・102(+103)のみ。104–109はRelinquish_Defaultにより
書き込まなくても標準状態で機能する(段階的開示)。

## 4. 計測量(AI/BI、読取専用)

### 室内

| Inst. | Object_Name | Units | 説明 |
|---|---|---|---|
| 201 | RoomTemperature | degrees-Celsius | 室温(乾球) |
| 202 | RoomRelativeHumidity | percent-relative-humidity | 室相対湿度 |
| 203 | RoomCO2Level | parts-per-million | 室CO2濃度 |
| 204 | RoomPMV | no-units | PMV(バイアス適用前の生値) |
| 205 | RoomPPD | percent | PPD(PMV−バイアスで評価した値。KPIと同一定義) |
| 206 | OccupantCount | no-units | 在室人数。※実建物では通常計測できない点に注意。ラッパー側で学生から隠す/見せるを選択可(CO2からの人数推定を教材にする場合は隠す) |

### AHU・外気

| Inst. | Object_Name | Units | 説明 |
|---|---|---|---|
| 211 | SupplyAirTemperature | degrees-Celsius | 給気温度 |
| 212 | SupplyAirRelativeHumidity | percent-relative-humidity | 給気相対湿度 |
| 213 | SupplyAirFlowRate | cubic-meters-per-hour | 給気風量 |
| 214 | OutdoorAirFlowRate | cubic-meters-per-hour | 外気導入量 |
| 215 | ReturnAirTemperature | degrees-Celsius | 還気温度 |
| 216 | ReturnAirCO2Level | parts-per-million | 還気CO2濃度 |
| 217 | WaterInletTemperature | degrees-Celsius | 冷温水入口温度(AR(1)外乱で変動する実際値) |
| 218 | WaterFlowRate | liters-per-minute | 冷温水流量 |
| 219 | CoilLoad | kilowatts | コイル処理熱量(瞬時) |
| 220 | FanElectricity | kilowatts | ファン消費電力(給気+還気、瞬時) |
| 221 | OutdoorTemperature | degrees-Celsius | 外気温度 |
| 222 | OutdoorRelativeHumidity | percent-relative-humidity | 外気相対湿度 |
| 223 | GlobalHorizontalRadiation | watts-per-square-meter | 水平面全天日射(参考) |
| 224 | HumidifierStatus | BI | 加湿器作動状態 |

### KPI(積算値)

| Inst. | Object_Name | Units | 説明 |
|---|---|---|---|
| 231 | IntegratedEnergy | kilowatt-hours | Q_cool/COP_c + Q_heat/COP_h + ファン電力 の積算 |
| 232 | IntegratedPPD | no-units(%·h) | 在室時PPDの時間積算 |
| 233 | IntegratedOccupantWeightedPPD | no-units(人·%·h) | 在室時PPD×在室人数の時間積算(倫理的問いの討論素材。採点への採用可否はsetting.ini `PPD_OCCUPANT_WEIGHTED`をラッパーが参照) |
| 234 | CO2ExcessTime | no-units(h) | 在室時にCO2>1,000 ppmだった時間の積算 |
| 235 | OccupiedTime | no-units(h) | 在室時間の積算(平均PPD=232÷235の算出用) |

KPIの重み付け(総合スコア化)はラッパー・授業側で行う。KPIはリセット(§5)でクリアされる。

## 5. シミュレーション管理

| Inst. | Object_Name | 型 | 説明 |
|---|---|---|---|
| 301 | AccelerationRate | AV | 加速度(実時間1秒あたりのシミュレーション秒数)。**0=停止**。起動時値はsetting.ini |
| 302 | PauseAtDateTime | DateTime Value(書込可) | 一時停止時刻。書込み後に加速度>0とすると、本体がこの時刻ちょうどで自停止(加速度を0に)する。ステップ実行の基盤(Shizuku2と同方式) |
| 303 | CurrentDateTime | DateTime Value(読取専用) | 現在のシミュレーション時刻(Device Local_Date/Timeの補助) |

### リセット — ReinitializeDeviceサービス

独自ポイントではなく、BACnet標準の **ReinitializeDevice** サービスで実現する。

| 引数 | 動作 |
|---|---|
| COLDSTART | setting.iniを再読込し、助走計算からやり直して初期状態へ完全復帰(乱数系列もシードから再初期化)。RLのエピソードリセット用 |
| WARMSTART | KPI積算(231–234)のみクリア。状態・時刻は維持(採点区間の切替用) |

COLDSTART時の助走計算(周期定常)を毎回実行すると重いため、**助走結果の初期状態は
シード・開始日が不変ならキャッシュする**(2回目以降のリセットは即時完了)。

## 6. ラッパーAPIとの対応(参考)

Pythonラッパー(Gymnasium互換)は上記を以下のように束ねる想定。

```python
env.reset()        # → ReinitializeDevice(COLDSTART)、初期観測を返す
env.step(action)   # → 101-103等へ書込み(priority 16)
                   #   → 302に現在時刻+CONTROL_INTERVALを書込み
                   #   → 301に加速度を書込み → 自停止を待つ(303をポーリング or COV)
                   #   → 観測・報酬を返す
obs                # ← 201-224(教材設定に応じ206等を隠蔽)
reward             # ← 231-234の増分から合成(232/233の選択はsetting.iniに従う)
```

学生向け簡易APIはさらにこの上で `emu.read("室温")` / `emu.write("弁開度", 0.6)` 程度の
語彙に落とす。BACnetのオブジェクトID・priority・ポーリングはすべてラッパーが隠蔽する。
