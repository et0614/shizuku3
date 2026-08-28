// Shizuku3 Web GUI クライアント（英語既定・日英切替）
const $ = id => document.getElementById(id);

const I18N = {
  en: {play: "▶ Play", pause: "❚❚ Pause", acc: "Acceleration", valve: "Valve position",
    fan: "Fan speed ratio", dmp: "OA damper", mode: "Mode", modes: ["Auto", "Cooling", "Heating"],
    on: "AHU on", bypass: "HEX bypass", reset: "Reset",
    humid: "Humidifier", humidsp: "Humid. setpoint", humiddb: "Deadband",
    confirm: "Reload setting.ini and restart from the initial state?",
    err: "Communication error: ", hint: " (check that Shizuku3.exe is running)",
    lost: "Connection to the server lost. Reconnecting...",
    chT: ["Room", "Supply", "Outdoor"], chC: ["Room CO2", "Limit 1000"],
    chR: ["Room", "Supply", "Outdoor"],
    yT: "Temperature [°C]", yC: "CO2 [ppm]", yR: "Relative humidity [%]", other: "日本語"},
  ja: {play: "▶ 再生", pause: "❚❚ 一時停止", acc: "加速度", valve: "弁開度",
    fan: "ファン回転数比", dmp: "外気ダンパ", mode: "モード", modes: ["自動", "冷房", "暖房"],
    on: "AHU運転", bypass: "HEXバイパス", reset: "リセット",
    humid: "加湿器", humidsp: "加湿設定湿度", humiddb: "差動",
    confirm: "setting.iniを再読込して初期状態に戻します。よろしいですか？",
    err: "通信エラー: ", hint: "（Shizuku3.exeが起動しているか確認してください）",
    lost: "サーバとの接続が切れました。再接続中...",
    chT: ["室温", "給気", "外気"], chC: ["室CO2", "基準1000"], chR: ["室", "給気", "外気"],
    yT: "温度[°C]", yC: "CO2[ppm]", yR: "相対湿度[%]", other: "English"},
};
let lang = "en";

//SVG内の動的テキストID（数値系は読込時に右揃え化する）
const NUMERIC_IDS = ["outdoor_temp","outdoor_rh","damper_pos","oa_flow","fan_ratio","fan_kw",
  "valve_pos","water_flow","water_temp","sa_temp","sa_rh","sa_flow","room_temp","room_rh",
  "co2","occupants","pmv","energy","ppd_ave","co2_excess"];
const TEXT_IDS = ["sim_date","sim_time","hex_state","humid_state"];
const texts = {};
const DYNAMIC_COLOR = "#fff3c4"; //動的値の文字色（静的ラベルと区別する薄い黄色）
let ws = null, playing = false;

fetch("/gui.svg").then(r => r.text()).then(s => {
  $("svgbox").innerHTML = s;
  //描画内容の実寸にviewBoxを横方向のみクロップ（右側の余白を除去。縦は元のviewBoxを維持）
  const svg = $("svgbox").querySelector("svg");
  try {
    const vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
    const bg = document.getElementById("background");
    if (bg) bg.style.display = "none";
    const b = svg.getBBox();
    if (bg) bg.style.display = "";
    if (vb.length === 4)
      svg.setAttribute("viewBox", `${b.x - 8} ${vb[1]} ${b.width + 16} ${vb[3]}`);
  } catch (e) { console.warn("viewBox crop failed:", e); }
  for (const id of [...NUMERIC_IDS, ...TEXT_IDS]) {
    const g = document.getElementById(id);
    if (!g) continue;
    const t = g.tagName === "text" ? g : g.querySelector("text");
    if (!t) continue;
    texts[id] = t;
    t.style.fill = DYNAMIC_COLOR;
    t.querySelectorAll("tspan").forEach(sp => sp.style.fill = DYNAMIC_COLOR);
    if (NUMERIC_IDS.includes(id)) {
      try { //右揃え化: 現在の右端座標を測ってtext-anchor=endに切替
        const b = t.getBBox();
        t.querySelectorAll("tspan").forEach(sp => { sp.removeAttribute("x"); sp.removeAttribute("y"); });
        t.setAttribute("text-anchor", "end");
        t.setAttribute("x", b.x + b.width);
        if (!t.getAttribute("y")) t.setAttribute("y", b.y + b.height * 0.8);
      } catch (e) { console.warn("anchor fix failed:", id, e); }
    }
  }
  connect();
});

//---- グラフ ------------------------------------------------------
function mkChart(ctx, colors, yTitle) {
  return new Chart(ctx, {type: "line",
    data: {labels: [], datasets: colors.map(c => ({label: "", data: [], borderColor: c,
      borderWidth: 1.5, pointRadius: 0, tension: 0}))},
    options: {animation: false, responsive: true, maintainAspectRatio: false,
      scales: {x: {ticks: {color: "#889", maxTicksLimit: 8}, grid: {color: "#242a36"}},
               y: {title: {display: true, text: yTitle, color: "#889"},
                   ticks: {color: "#889"}, grid: {color: "#242a36"}}},
      plugins: {legend: {labels: {color: "#aab", boxWidth: 12}}}}});
}
const cTemp = mkChart($("cTemp"), ["#ffb74d", "#4fc3f7", "#4caf50"], "");
const cCO2 = mkChart($("cCO2"), ["#66bb6a", "#e5737366"], "");
const cRH = mkChart($("cRH"), ["#ffb74d", "#4fc3f7", "#4caf50"], "");

function addPoint(p) {
  const push = (ch, vals) => {
    ch.data.labels.push(p.label);
    vals.forEach((v, i) => ch.data.datasets[i].data.push(v));
    if (1440 < ch.data.labels.length) {
      ch.data.labels.shift();
      ch.data.datasets.forEach(d => d.data.shift());
    }
  };
  push(cTemp, [p.room_temp, p.sa_temp, p.outdoor_temp]);
  push(cCO2, [p.co2, 1000]);
  push(cRH, [p.room_rh, p.sa_rh, p.outdoor_rh]);
}
function redraw() { cTemp.update(); cCO2.update(); cRH.update(); }

//---- 言語切替 ----------------------------------------------------
function applyLang() {
  const L = I18N[lang];
  document.querySelectorAll("[data-i18n]").forEach(e => e.textContent = L[e.dataset.i18n]);
  const opts = $("mode").options;
  for (let i = 0; i < 3; i++) opts[i].text = L.modes[i];
  $("langbtn").textContent = L.other;
  [[cTemp, L.chT, L.yT], [cCO2, L.chC, L.yC], [cRH, L.chR, L.yR]].forEach(([ch, ls, y]) => {
    ch.data.datasets.forEach((d, i) => d.label = ls[i]);
    ch.options.scales.y.title.text = y;
    ch.update();
  });
}
$("langbtn").onclick = () => { lang = lang === "en" ? "ja" : "en"; applyLang(); };
applyLang();

//---- WebSocket ---------------------------------------------------
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.type === "history") {
      [cTemp, cCO2, cRH].forEach(ch => { ch.data.labels = [];
        ch.data.datasets.forEach(d => d.data = []); });
      m.data.forEach(addPoint);
      redraw();
    } else if (m.type === "update") {
      $("status").textContent = "";
      for (const [id, v] of Object.entries(m.data))
        if (texts[id]) texts[id].textContent = v;
      playing = 0 < parseFloat(m.data.acc);
      if (m.point) { addPoint(m.point); redraw(); }
    } else if (m.type === "error") {
      $("status").textContent = I18N[lang].err + m.message + I18N[lang].hint;
    }
  };
  ws.onclose = () => {
    $("status").textContent = I18N[lang].lost;
    setTimeout(connect, 2000);
  };
}
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

//---- 操作パネル --------------------------------------------------
const accVal = () => Math.max(1, Math.min(3600, Math.round(10 ** parseFloat($("acc").value))));
$("acc").oninput = () => $("accv").textContent = accVal();
$("acc").onchange = () => { if (playing) send({cmd: "play", value: accVal()}); };
$("play").onclick = () => send({cmd: "play", value: accVal()});
$("stop").onclick = () => send({cmd: "stop"});
$("reset").onclick = () => { if (confirm(I18N[lang].confirm)) send({cmd: "reset"}); };
const slider = (id, lbl, name, fmt) => {
  $(id).oninput = () => $(lbl).textContent = fmt(parseFloat($(id).value));
  $(id).onchange = () => send({cmd: "write", name: name, value: parseFloat($(id).value)});
};
slider("valve", "valvev", "弁開度", v => v.toFixed(2));
slider("fan", "fanv", "ファン回転数比", v => v.toFixed(2));
slider("dmp", "dmpv", "外気ダンパ開度", v => v.toFixed(2));
slider("humidsp", "humidspv", "加湿設定湿度", v => v.toFixed(0));
slider("humiddb", "humiddbv", "加湿差動", v => v.toFixed(0));
$("humid").onchange = () => send({cmd: "write", name: "加湿有効", value: $("humid").checked});
$("mode").onchange = () => send({cmd: "write", name: "冷暖モード", value: parseInt($("mode").value)});
$("onoff").onchange = () => send({cmd: "write", name: "発停", value: $("onoff").checked});
$("bypass").onchange = () => send({cmd: "write", name: "全熱交バイパス", value: $("bypass").checked});
