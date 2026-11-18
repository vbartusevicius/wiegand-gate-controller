(() => {
  const byId = (id) => document.getElementById(id);
  const state = { users: [], lastUnknown: null, activeTab: "overview", config: null };

  const MODE_LABELS = {
    gate_dual: "Dual-Relay Gate",
    gate_pulse: "Single-Button Step",
    door: "Single Door Lock",
    dual_door: "Two Doors",
  };

  const SENSOR_LABELS = {
    single_reed: "Single Contact (IN1)",
    dual_limit: "Dual Limits (IN1/IN2)",
    roger_b70: "Blinking Status + Confirm",
    timer_fallback: "Timer Estimate",
  };

  const MODE_HINTS = {
    gate_dual: "R1 pulses to Open, R2 pulses to Close. Triggering while open/opening closes the gate.",
    gate_pulse: "R1 alternates Open -> Stop -> Close on one motor input. R2 triggers partial/pedestrian opening.",
    door: "R1 unlocks the primary door strike or maglock. R2 is available for auxiliary/pedestrian output.",
    dual_door: "R1 controls Door 1 and R2 controls Door 2 based on each user's Relay Target.",
  };

  const SENSOR_HINTS = {
    single_reed: "Magnetic contact on IN1 (active = Closed, inactive = Open).",
    dual_limit: "Closed limit on IN1, Open limit on IN2. Both active at once reports Fault.",
    roger_b70: "IN1 reads controller status lamp (0V=Closed, Blink=Moving, 24V=Open). IN2 optional confirm.",
    timer_fallback: "No position switches; estimates Open/Closed from Full Travel Time.",
  };

  const FLOW_SCENARIOS = [
    {
      id: "auto_close",
      title: "Opens on card, closes itself",
      desc: "Card pulses R1 to open; gate/door auto-closes by its own timer or strike.",
      apply: { mode: "door", r1: 800, r2: 600, hold: false },
      match: (r) => r.mode === "door" && !r.hold,
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="2" y="14" width="40" height="34" rx="5" stroke="#3b82f6" stroke-width="1.5" fill="#171f27"/>
        <text x="22" y="35" text-anchor="middle" fill="#e8eef4" font-size="10.5" font-weight="600" font-family="sans-serif">CARD</text>
        <path d="M42 31 H58" stroke="#22c55e" stroke-width="1.8"/>
        <polygon points="57,27 63,31 57,35" fill="#22c55e"/>
        <rect x="64" y="14" width="56" height="34" rx="5" stroke="#22c55e" stroke-width="1.5" fill="#171f27"/>
        <text x="92" y="29" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="600" font-family="sans-serif">R1 PULSE</text>
        <text x="92" y="42" text-anchor="middle" fill="#8fa1b3" font-size="9.5" font-family="sans-serif">OPEN</text>
        <path d="M122 22 C148 4, 174 12, 174 31 C174 50, 148 58, 124 42" stroke="#f59e0b" stroke-width="1.6" stroke-dasharray="3 2"/>
        <text x="148" y="29" text-anchor="middle" fill="#f59e0b" font-size="9.5" font-weight="600" font-family="sans-serif">AUTO</text>
        <text x="148" y="41" text-anchor="middle" fill="#f59e0b" font-size="9" font-weight="600" font-family="sans-serif">CLOSE</text>
      </svg>`,
    },
    {
      id: "open_close_cards",
      title: "Opens & closes on card reads",
      desc: "1st card read pulses R1 (Open); 2nd card read pulses R2 (Close).",
      apply: { mode: "gate_dual", r1: 600, r2: 600, hold: false },
      match: (r) => r.mode === "gate_dual" && !r.hold,
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="2" y="5" width="46" height="23" rx="4" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="25" y="20" text-anchor="middle" fill="#e8eef4" font-size="9.5" font-weight="600" font-family="sans-serif">CARD 1</text>
        <path d="M48 16 H64" stroke="#22c55e" stroke-width="1.6"/>
        <rect x="65" y="5" width="58" height="23" rx="4" stroke="#22c55e" stroke-width="1.4" fill="#171f27"/>
        <text x="94" y="20" text-anchor="middle" fill="#22c55e" font-size="9.5" font-weight="600" font-family="sans-serif">R1 OPEN</text>
        <rect x="2" y="36" width="46" height="23" rx="4" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="25" y="51" text-anchor="middle" fill="#e8eef4" font-size="9.5" font-weight="600" font-family="sans-serif">CARD 2</text>
        <path d="M48 47 H64" stroke="#f59e0b" stroke-width="1.6"/>
        <rect x="65" y="36" width="58" height="23" rx="4" stroke="#f59e0b" stroke-width="1.4" fill="#171f27"/>
        <text x="94" y="51" text-anchor="middle" fill="#f59e0b" font-size="9.5" font-weight="600" font-family="sans-serif">R2 CLOSE</text>
        <rect x="133" y="10" width="45" height="44" rx="5" stroke="#8fa1b3" stroke-width="1.4" fill="#171f27"/>
        <path d="M123 16 H133 M123 47 H133" stroke="#8fa1b3" stroke-width="1.4"/>
        <text x="155" y="29" text-anchor="middle" fill="#e8eef4" font-size="10" font-weight="600" font-family="sans-serif">GATE</text>
        <text x="155" y="42" text-anchor="middle" fill="#8fa1b3" font-size="8.5" font-family="sans-serif">OPEN/CLS</text>
      </svg>`,
    },
    {
      id: "step_cycle",
      title: "1-button step (Open/Stop/Close)",
      desc: "Every card read pulses R1 to step the motor; R2 handles partial pedestrian pass.",
      apply: { mode: "gate_pulse", r1: 600, r2: 600, hold: false },
      match: (r) => r.mode === "gate_pulse" && !r.hold,
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="2" y="15" width="42" height="32" rx="4" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="23" y="35" text-anchor="middle" fill="#e8eef4" font-size="10" font-weight="600" font-family="sans-serif">CARD</text>
        <path d="M44 31 H57" stroke="#22c55e" stroke-width="1.6"/>
        <rect x="58" y="15" width="34" height="32" rx="4" stroke="#22c55e" stroke-width="1.4" fill="#171f27"/>
        <text x="75" y="35" text-anchor="middle" fill="#22c55e" font-size="11" font-weight="600" font-family="sans-serif">R1</text>
        <path d="M92 31 H103" stroke="#8fa1b3" stroke-width="1.4"/>
        <rect x="104" y="4" width="74" height="56" rx="5" stroke="#8fa1b3" stroke-width="1.3" fill="#171f27"/>
        <text x="141" y="20" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="600" font-family="sans-serif">OPEN</text>
        <text x="141" y="35" text-anchor="middle" fill="#3b82f6" font-size="10" font-weight="600" font-family="sans-serif">↓ STOP ↓</text>
        <text x="141" y="50" text-anchor="middle" fill="#f59e0b" font-size="10" font-weight="600" font-family="sans-serif">CLOSE</text>
      </svg>`,
    },
    {
      id: "hold_latch",
      title: "Hold open / Maglock latch",
      desc: "Open keeps R1 active (unlocked or held open) until Close is triggered.",
      apply: { mode: "door", r1: 3000, r2: 1000, hold: true },
      match: (r) => r.hold,
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="2" y="16" width="52" height="34" rx="4" stroke="#22c55e" stroke-width="1.4" fill="#171f27"/>
        <text x="28" y="31" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="600" font-family="sans-serif">OPEN</text>
        <text x="28" y="44" text-anchor="middle" fill="#8fa1b3" font-size="9" font-family="sans-serif">R1 = ON</text>
        <path d="M54 33 H122" stroke="#22c55e" stroke-width="2.6"/>
        <text x="88" y="24" text-anchor="middle" fill="#e8eef4" font-size="9.5" font-weight="600" font-family="sans-serif">LATCHED</text>
        <rect x="122" y="16" width="56" height="34" rx="4" stroke="#f59e0b" stroke-width="1.4" fill="#171f27"/>
        <text x="150" y="31" text-anchor="middle" fill="#f59e0b" font-size="10" font-weight="600" font-family="sans-serif">CLOSE</text>
        <text x="150" y="44" text-anchor="middle" fill="#8fa1b3" font-size="9" font-family="sans-serif">R1 = OFF</text>
      </svg>`,
    },
    {
      id: "two_doors",
      title: "Two separate doors / gates",
      desc: "Primary users trigger R1 (Door 1); Pedestrian/Relay 2 users trigger R2 (Door 2).",
      apply: { mode: "dual_door", r1: 3000, r2: 3000, hold: false },
      match: (r) => r.mode === "dual_door" && !r.hold,
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="2" y="14" width="52" height="36" rx="4" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="28" y="30" text-anchor="middle" fill="#e8eef4" font-size="10" font-weight="600" font-family="sans-serif">USER</text>
        <text x="28" y="43" text-anchor="middle" fill="#8fa1b3" font-size="8.5" font-family="sans-serif">TARGET</text>
        <path d="M54 25 L80 16 M54 39 L80 48" stroke="#8fa1b3" stroke-width="1.5"/>
        <rect x="81" y="4" width="97" height="24" rx="4" stroke="#22c55e" stroke-width="1.4" fill="#171f27"/>
        <text x="129" y="20" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="600" font-family="sans-serif">R1 → DOOR 1</text>
        <rect x="81" y="36" width="97" height="24" rx="4" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="129" y="52" text-anchor="middle" fill="#3b82f6" font-size="10" font-weight="600" font-family="sans-serif">R2 → DOOR 2</text>
      </svg>`,
    },
  ];

  const SENSOR_SCENARIOS = [
    {
      id: "single_reed",
      title: "1 Reed / Magnetic Contact",
      desc: "Closed when IN1 is active, Open otherwise.",
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="4" y="16" width="24" height="30" rx="3" stroke="#8fa1b3" stroke-width="1.4" fill="#171f27"/>
        <rect x="36" y="21" width="14" height="20" rx="2" stroke="#22c55e" stroke-width="1.4" fill="#171f27"/>
        <path d="M50 31 H82" stroke="#22c55e" stroke-width="1.8"/>
        <rect x="83" y="12" width="94" height="38" rx="5" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="130" y="28" text-anchor="middle" fill="#e8eef4" font-size="10" font-weight="600" font-family="sans-serif">SENSORS IN1</text>
        <text x="130" y="42" text-anchor="middle" fill="#22c55e" font-size="9.5" font-weight="600" font-family="sans-serif">ON = CLOSED</text>
      </svg>`,
    },
    {
      id: "dual_limit",
      title: "2 Limit Switches",
      desc: "IN1 = Closed end-stop, IN2 = Open end-stop.",
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <rect x="2" y="7" width="54" height="22" rx="4" stroke="#22c55e" stroke-width="1.3" fill="#171f27"/>
        <text x="29" y="22" text-anchor="middle" fill="#22c55e" font-size="9.5" font-weight="600" font-family="sans-serif">CLOSED</text>
        <rect x="2" y="35" width="54" height="22" rx="4" stroke="#f59e0b" stroke-width="1.3" fill="#171f27"/>
        <text x="29" y="50" text-anchor="middle" fill="#f59e0b" font-size="9.5" font-weight="600" font-family="sans-serif">OPEN</text>
        <path d="M56 18 H82 M56 46 H82" stroke="#8fa1b3" stroke-width="1.5"/>
        <rect x="83" y="7" width="94" height="50" rx="5" stroke="#3b82f6" stroke-width="1.4" fill="#171f27"/>
        <text x="130" y="26" text-anchor="middle" fill="#22c55e" font-size="10" font-weight="600" font-family="sans-serif">IN1 = Closed</text>
        <text x="130" y="46" text-anchor="middle" fill="#f59e0b" font-size="10" font-weight="600" font-family="sans-serif">IN2 = Open</text>
      </svg>`,
    },
    {
      id: "roger_b70",
      title: "Blinking Status Output",
      desc: "IN1: 0V=Closed, Blink=Moving, 24V=Open.",
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <path d="M6 42 H38 V14 H52 V42 H66 V14 H80 V42 H94 V14 H172" stroke="#3b82f6" stroke-width="2"/>
        <text x="24" y="57" text-anchor="middle" fill="#22c55e" font-size="9.5" font-weight="600" font-family="sans-serif">CLOSED</text>
        <text x="78" y="57" text-anchor="middle" fill="#3b82f6" font-size="9.5" font-weight="600" font-family="sans-serif">MOVING</text>
        <text x="142" y="57" text-anchor="middle" fill="#f59e0b" font-size="9.5" font-weight="600" font-family="sans-serif">OPEN</text>
      </svg>`,
    },
    {
      id: "timer_fallback",
      title: "No Sensors (Timer)",
      desc: "Estimates Open/Closed using Travel Time.",
      svg: `<svg viewBox="0 0 180 64" fill="none">
        <circle cx="34" cy="31" r="21" stroke="#3b82f6" stroke-width="1.7" fill="#171f27"/>
        <path d="M34 17 V31 L45 37" stroke="#e8eef4" stroke-width="2" stroke-linecap="round"/>
        <path d="M57 31 H79" stroke="#8fa1b3" stroke-width="1.6" stroke-dasharray="3 2"/>
        <rect x="80" y="12" width="97" height="38" rx="5" stroke="#8fa1b3" stroke-width="1.3" fill="#171f27"/>
        <text x="128" y="28" text-anchor="middle" fill="#e8eef4" font-size="10" font-weight="600" font-family="sans-serif">TRAVEL TIME</text>
        <text x="128" y="42" text-anchor="middle" fill="#8fa1b3" font-size="9.5" font-family="sans-serif">ESTIMATED</text>
      </svg>`,
    },
  ];

  function notify(msg, isErr = false) {
    const el = byId("toast");
    el.textContent = msg;
    el.className = isErr ? "toast err" : "toast";
    setTimeout(() => el.classList.add("hidden"), 4000);
  }

  async function api(url, opts = {}) {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  function setPill(id, label, on) {
    const el = byId(id);
    el.textContent = `${label}: ${on ? "ON" : "OFF"}`;
    el.className = on ? "pill on" : "pill";
  }

  function switchTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));
    if (tab === "users") loadUsers();
    if (tab === "settings" || tab === "network") loadConfig();
  }

  function adaptOverviewToMode(mode, sensor) {
    const isGate = mode === "gate_dual" || mode === "gate_pulse";
    const isDualDoor = mode === "dual_door";
    byId("ctl-title").textContent = isGate ? "Gate Control" : isDualDoor ? "Doors Control" : "Door Control";
    byId("btn-act-open").textContent = isDualDoor ? "Door 1" : "Open";
    byId("btn-act-close").textContent = "Close";
    byId("btn-act-close").classList.toggle("hidden", isDualDoor);
    byId("btn-act-stop").classList.toggle("hidden", !isGate);
    byId("btn-act-trigger").textContent = mode === "gate_pulse" ? "Step" : "Pulse";
    byId("btn-act-trigger").classList.toggle("hidden", isDualDoor);
    byId("btn-act-ped").textContent = isDualDoor ? "Door 2" : isGate ? "Pedestrian" : "Aux (R2)";

    const r1Lbl = mode === "gate_dual" ? "R1 Open" : mode === "gate_pulse" ? "R1 Step" : isDualDoor ? "R1 Door 1" : "R1 Lock";
    const r2Lbl = mode === "gate_dual" ? "R2 Close" : isDualDoor ? "R2 Door 2" : "R2 Ped/Aux";
    const in1Lbl = sensor === "roger_b70" ? "IN1 Status" : "IN1 Closed";
    const in2Lbl = sensor === "dual_limit" ? "IN2 Open" : sensor === "roger_b70" ? "IN2 Confirm" : "IN2";
    return { r1Lbl, r2Lbl, in1Lbl, in2Lbl, in3Lbl: "IN3 Exit" };
  }

  function renderScenarioCards() {
    const flowHost = byId("flow-cards");
    flowHost.innerHTML = FLOW_SCENARIOS.map(
      (s) => `<button type="button" class="sc-card" data-flow="${s.id}">
        ${s.svg}
        <span class="sc-title">${s.title}</span>
        <span class="sc-desc">${s.desc}</span>
      </button>`
    ).join("");
    flowHost.querySelectorAll("[data-flow]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sc = FLOW_SCENARIOS.find((x) => x.id === btn.dataset.flow);
        if (!sc) return;
        byId("c-relay-mode").value = sc.apply.mode;
        byId("c-r1-ms").value = sc.apply.r1;
        byId("c-r2-ms").value = sc.apply.r2;
        byId("c-r1-hold").checked = sc.apply.hold;
        updateSettingsVisibility();
      });
    });

    const sensHost = byId("sensor-cards");
    sensHost.innerHTML = SENSOR_SCENARIOS.map(
      (s) => `<button type="button" class="sc-card" data-sensor="${s.id}">
        ${s.svg}
        <span class="sc-title">${s.title}</span>
        <span class="sc-desc">${s.desc}</span>
      </button>`
    ).join("");
    sensHost.querySelectorAll("[data-sensor]").forEach((btn) => {
      btn.addEventListener("click", () => {
        byId("c-sensor-mode").value = btn.dataset.sensor;
        updateSettingsVisibility();
      });
    });
  }

  function renderLiveDiagram(rMode, sMode, r1Hold, in3En, in3Ped) {
    const r1Txt = rMode === "gate_dual" ? "Open Motor (Pulse)" : rMode === "gate_pulse" ? "Step Motor (Open/Stop/Close)" : rMode === "dual_door" ? "Door 1 Lock" : r1Hold ? "Lock Output (Latched)" : "Lock Strike (Pulse)";
    const r2Txt = rMode === "gate_dual" ? "Close Motor (Pulse)" : rMode === "gate_pulse" ? "Pedestrian / Partial" : rMode === "dual_door" ? "Door 2 Lock" : "Aux Output";
    const in1Txt = sMode === "single_reed" ? "Closed Contact" : sMode === "dual_limit" ? "Closed Limit" : sMode === "roger_b70" ? "Status (0V/Blink/24V)" : "Unused";
    const in2Txt = sMode === "dual_limit" ? "Open Limit" : sMode === "roger_b70" ? "Confirm" : "Unused";
    const in3Txt = !in3En ? "Disabled" : in3Ped ? "Exit Button -> Pedestrian (R2)" : "Exit Button -> Primary";

    byId("live-diagram").innerHTML = `
      <svg viewBox="0 0 820 180" fill="none">
        <rect x="8" y="12" width="200" height="156" rx="8" stroke="#3b82f6" stroke-width="1.6" fill="#171f27"/>
        <text x="108" y="35" text-anchor="middle" fill="#e8eef4" font-size="13" font-weight="bold" font-family="sans-serif">WIEGAND READER</text>
        <text x="108" y="57" text-anchor="middle" fill="#8fa1b3" font-size="11.5" font-family="sans-serif">WIEGAND: 12V · GND · D0 · D1</text>
        <text x="108" y="76" text-anchor="middle" fill="#8fa1b3" font-size="11.5" font-family="sans-serif">LED · BEEP · PWR: V+ · GND</text>
        <rect x="24" y="94" width="168" height="56" rx="6" stroke="#2a3744" fill="#0f1419"/>
        <text x="108" y="118" text-anchor="middle" fill="#22c55e" font-size="12" font-weight="600" font-family="sans-serif">Card / Fob / PIN</text>
        <text x="108" y="137" text-anchor="middle" fill="#8fa1b3" font-size="11" font-family="sans-serif">Auto-detected bits</text>
        <path d="M208 90 H248" stroke="#3b82f6" stroke-width="2"/>

        <rect x="248" y="12" width="236" height="156" rx="8" stroke="#22c55e" stroke-width="1.6" fill="#171f27"/>
        <text x="366" y="35" text-anchor="middle" fill="#e8eef4" font-size="13" font-weight="bold" font-family="sans-serif">BOX TERMINALS</text>
        <rect x="262" y="47" width="208" height="25" rx="4" fill="#1e2933"/>
        <text x="366" y="64" text-anchor="middle" fill="#22c55e" font-size="11.5" font-weight="600" font-family="sans-serif">RELAY 1 (COM / NO / NC)</text>
        <rect x="262" y="77" width="208" height="25" rx="4" fill="#1e2933"/>
        <text x="366" y="94" text-anchor="middle" fill="#f59e0b" font-size="11.5" font-weight="600" font-family="sans-serif">RELAY 2 (COM / NO / NC)</text>
        <rect x="262" y="107" width="208" height="25" rx="4" fill="#1e2933"/>
        <text x="366" y="124" text-anchor="middle" fill="#3b82f6" font-size="11.5" font-weight="600" font-family="sans-serif">SENSORS (IN1+/- · IN2+/-)</text>
        <rect x="262" y="137" width="208" height="25" rx="4" fill="#1e2933"/>
        <text x="366" y="154" text-anchor="middle" fill="#8fa1b3" font-size="11.5" font-weight="600" font-family="sans-serif">EXIT / 12V (IN3+/- · +12V · GND)</text>

        <path d="M484 59 H524 M484 89 H524 M484 119 H524 M484 149 H524" stroke="#8fa1b3" stroke-width="1.8"/>
        <rect x="524" y="47" width="286" height="25" rx="4" stroke="#22c55e" fill="#0f1419"/>
        <text x="667" y="64" text-anchor="middle" fill="#e8eef4" font-size="11.5" font-weight="600" font-family="sans-serif">${r1Txt}</text>
        <rect x="524" y="77" width="286" height="25" rx="4" stroke="#f59e0b" fill="#0f1419"/>
        <text x="667" y="94" text-anchor="middle" fill="#e8eef4" font-size="11.5" font-weight="600" font-family="sans-serif">${r2Txt}</text>
        <rect x="524" y="107" width="286" height="25" rx="4" stroke="#3b82f6" fill="#0f1419"/>
        <text x="667" y="124" text-anchor="middle" fill="#e8eef4" font-size="11.5" font-weight="600" font-family="sans-serif">IN1: ${in1Txt}${sMode === "dual_limit" || sMode === "roger_b70" ? " · IN2: " + in2Txt : ""}</text>
        <rect x="524" y="137" width="286" height="25" rx="4" stroke="#2a3744" fill="#0f1419"/>
        <text x="667" y="154" text-anchor="middle" fill="${in3En ? "#e8eef4" : "#8fa1b3"}" font-size="11.5" font-weight="600" font-family="sans-serif">${in3Txt}</text>
      </svg>`;
  }

  function updateSettingsVisibility() {
    const rMode = byId("c-relay-mode").value;
    const sMode = byId("c-sensor-mode").value;
    const r1Hold = byId("c-r1-hold").checked;
    const in3En = byId("c-in3-en").checked;
    const in3Ped = byId("c-in3-ped").checked;

    byId("hint-relay-mode").textContent = MODE_HINTS[rMode] || "";
    byId("hint-sensor-mode").textContent = SENSOR_HINTS[sMode] || "";

    const showTravel = rMode === "gate_dual" || rMode === "gate_pulse" || sMode === "dual_limit" || sMode === "timer_fallback" || sMode === "roger_b70";
    byId("grp-travel").classList.toggle("hidden", !showTravel);
    byId("grp-blink").classList.toggle("hidden", sMode !== "roger_b70");
    byId("grp-in-inv").classList.toggle("hidden", sMode === "timer_fallback");
    byId("grp-in3").classList.toggle("hidden", !in3En);

    const rSnapshot = { mode: rMode, hold: r1Hold, r1: Number(byId("c-r1-ms").value || 0) };
    document.querySelectorAll("[data-flow]").forEach((btn) => {
      const sc = FLOW_SCENARIOS.find((x) => x.id === btn.dataset.flow);
      btn.classList.toggle("active", Boolean(sc && sc.match(rSnapshot)));
    });
    document.querySelectorAll("[data-sensor]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.sensor === sMode);
    });

    renderLiveDiagram(rMode, sMode, r1Hold, in3En, in3Ped);
  }

  async function loadStatus() {
    try {
      const s = await api("/api/status");
      byId("hdr-name").textContent = s.device_name || "Wiegand Gateway";
      byId("hdr-meta").textContent = `FW ${s.fw_version} · Up ${s.uptime_s}s · ${s.network.ip || "AP"}`;
      byId("hdr-dot").className = s.network.wifi_connected ? "dot ok" : "dot";

      const badge = byId("gate-badge");
      badge.textContent = (s.gate.state || "unknown").replace("_", " ");
      badge.className = `badge ${s.gate.state || "unknown"}`;

      const lbl = adaptOverviewToMode(s.gate.mode, s.gate.sensor_mode);
      setPill("io-r1", lbl.r1Lbl, s.gate.relay1);
      setPill("io-r2", lbl.r2Lbl, s.gate.relay2);
      setPill("io-in1", lbl.in1Lbl, s.gate.in1);
      setPill("io-in2", lbl.in2Lbl, s.gate.in2);
      setPill("io-in3", lbl.in3Lbl, s.gate.in3);

      byId("st-mode").textContent = MODE_LABELS[s.gate.mode] || s.gate.mode;
      byId("st-sensor").textContent = SENSOR_LABELS[s.gate.sensor_mode] || s.gate.sensor_mode;
      byId("st-vin").textContent = `${Number(s.vin_v || 0).toFixed(2)} V`;
      byId("st-wifi").textContent = s.network.ap_mode
        ? "AP Setup (192.168.4.1)"
        : s.network.wifi_connected
          ? `${s.network.ip} (${s.network.rssi} dBm)`
          : "Disconnected";
      byId("st-mqtt").textContent = s.network.mqtt_connected ? "Connected" : "Offline";
      byId("st-users").textContent = String(s.users_count || 0);

      const unk = s.last_unknown;
      const banner = byId("learn-banner");
      if (unk && unk.code) {
        state.lastUnknown = unk;
        byId("learn-code").textContent = unk.code;
        byId("learn-bits").textContent = unk.bits || "?";
        banner.classList.remove("hidden");
      } else {
        state.lastUnknown = null;
        banner.classList.add("hidden");
      }
    } catch (err) {
      notify(`Status error: ${err.message}`, true);
    }
  }

  async function loadEvents() {
    try {
      const data = await api("/api/events");
      const tbody = byId("events-body");
      tbody.innerHTML = "";
      for (const ev of data.events || []) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${(ev.ts / 1000).toFixed(1)}s</td><td>${ev.type}</td><td>${ev.source}</td><td>${ev.user}</td><td><code>${ev.code}</code></td>`;
        tbody.appendChild(tr);
      }
    } catch (err) {
      notify(`Events error: ${err.message}`, true);
    }
  }

  function renderUsers() {
    const q = (byId("user-search").value || "").toLowerCase();
    const tbody = byId("users-body");
    tbody.innerHTML = "";
    const filtered = state.users.filter(
      (u) => !q || u.name.toLowerCase().includes(q) || u.card.toLowerCase().includes(q)
    );
    byId("users-count").textContent = String(state.users.length);
    for (const u of filtered) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${u.name}</td>
        <td><code>${u.card || "—"}</code></td>
        <td><code>${u.pin ? "****" : "—"}</code></td>
        <td>${u.target}</td>
        <td>${u.hits}</td>
        <td>${u.enabled ? "Active" : "Disabled"}</td>
        <td class="row">
          <button class="btn small" data-edit="${u.id}">Edit</button>
          <button class="btn small danger" data-del="${u.id}">Delete</button>
        </td>`;
      tbody.appendChild(tr);
    }
    tbody.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const u = state.users.find((x) => x.id === Number(btn.dataset.edit));
        if (!u) return;
        byId("u-id").value = u.id;
        byId("u-name").value = u.name;
        byId("u-card").value = u.card;
        byId("u-pin").value = u.pin;
        byId("u-target").value = u.target;
        byId("u-enabled").checked = u.enabled;
        byId("user-form-title").textContent = `Edit User #${u.id}`;
      });
    });
    tbody.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/users?id=${btn.dataset.del}`, { method: "DELETE" });
          notify("User removed");
          loadUsers();
          loadStatus();
        } catch (err) {
          notify(`Delete failed: ${err.message}`, true);
        }
      });
    });
  }

  async function loadUsers() {
    try {
      const data = await api("/api/users");
      state.users = data.users || [];
      renderUsers();
    } catch (err) {
      notify(`Users load failed: ${err.message}`, true);
    }
  }

  async function loadConfig() {
    try {
      const c = await api("/api/config");
      state.config = c;
      byId("c-dev-name").value = c.device_name || "";
      byId("c-relay-mode").value = c.relay.mode;
      byId("c-r1-ms").value = c.relay.relay1_pulse_ms;
      byId("c-r2-ms").value = c.relay.relay2_pulse_ms;
      byId("c-travel-ms").value = c.relay.travel_time_ms;
      byId("c-r1-hold").checked = c.relay.relay1_hold_open;
      byId("c-r1-inv").checked = c.relay.relay1_inverted;
      byId("c-r2-inv").checked = c.relay.relay2_inverted;

      byId("c-sensor-mode").value = c.sensor.mode;
      byId("c-sc-blink").value = c.sensor.sc_blink_timeout_ms;
      byId("c-cor-open").checked = c.sensor.cor_indicates_open;
      byId("c-in1-inv").checked = c.sensor.in1_inverted;
      byId("c-in2-inv").checked = c.sensor.in2_inverted;
      byId("c-in3-en").checked = c.sensor.in3_enabled;
      byId("c-in3-ped").checked = c.sensor.in3_pedestrian;
      byId("c-in3-inv").checked = c.sensor.in3_inverted;

      byId("c-wg-bits").value = String(c.reader.wiegand_bits);
      byId("c-wg-beep-ms").value = c.reader.granted_beep_ms;
      byId("c-wg-led-ms").value = c.reader.granted_led_ms;
      byId("c-wg-denied").value = c.reader.denied_beeps;
      byId("c-pin-to").value = c.reader.pin_timeout_ms;
      byId("c-keypad-en").checked = c.reader.keypad_enabled;
      byId("c-led-low").checked = c.reader.led_active_low;
      byId("c-beep-low").checked = c.reader.beep_active_low;

      byId("c-wifi-ssid").value = c.wifi.ssid || "";
      byId("c-wifi-host").value = c.wifi.hostname || "";
      byId("c-mqtt-en").checked = c.mqtt.enabled;
      byId("c-mqtt-host").value = c.mqtt.host || "";
      byId("c-mqtt-port").value = c.mqtt.port || 1883;
      byId("c-mqtt-user").value = c.mqtt.username || "";
      byId("c-mqtt-topic").value = c.mqtt.base_topic || "";
      byId("c-mqtt-ha-pfx").value = c.mqtt.discovery_prefix || "homeassistant";
      byId("c-mqtt-ha").checked = c.mqtt.ha_discovery;
      updateSettingsVisibility();
    } catch (err) {
      notify(`Config load failed: ${err.message}`, true);
    }
  }

  async function saveConfigPayload(payload, okMsg) {
    try {
      await api("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      byId("c-wifi-pass").value = "";
      byId("c-mqtt-pass").value = "";
      notify(okMsg);
      loadStatus();
    } catch (err) {
      notify(`Save config failed: ${err.message}`, true);
    }
  }

  async function sendAction(action) {
    try {
      await api("/api/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      notify(`Action: ${action}`);
      loadStatus();
      loadEvents();
    } catch (err) {
      notify(`Action failed: ${err.message}`, true);
    }
  }

  function clearUserForm() {
    byId("u-id").value = "0";
    byId("u-name").value = "";
    byId("u-card").value = "";
    byId("u-pin").value = "";
    byId("u-target").value = "primary";
    byId("u-enabled").checked = true;
    byId("user-form-title").textContent = "Add Key / User";
  }

  function bindEvents() {
    document.querySelectorAll(".tab").forEach((b) =>
      b.addEventListener("click", () => switchTab(b.dataset.tab))
    );
    document.querySelectorAll("[data-act]").forEach((b) =>
      b.addEventListener("click", () => sendAction(b.dataset.act))
    );
    ["c-relay-mode", "c-sensor-mode", "c-r1-hold", "c-in3-en", "c-in3-ped"].forEach((id) =>
      byId(id).addEventListener("change", updateSettingsVisibility)
    );

    byId("btn-refresh-events").addEventListener("click", loadEvents);
    byId("user-search").addEventListener("input", renderUsers);
    byId("btn-user-cancel").addEventListener("click", clearUserForm);
    byId("btn-fill-scan").addEventListener("click", () => {
      if (state.lastUnknown) byId("u-card").value = state.lastUnknown.code;
    });
    byId("btn-learn-add").addEventListener("click", () => {
      switchTab("users");
      if (state.lastUnknown) byId("u-card").value = state.lastUnknown.code;
    });
    byId("btn-learn-dismiss").addEventListener("click", () => sendAction("clear_unknown"));

    byId("user-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api("/api/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: Number(byId("u-id").value || 0),
            name: byId("u-name").value.trim(),
            card: byId("u-card").value.trim(),
            pin: byId("u-pin").value.trim(),
            target: byId("u-target").value,
            enabled: byId("u-enabled").checked,
          }),
        });
        notify("User saved");
        clearUserForm();
        loadUsers();
        loadStatus();
      } catch (err) {
        notify(`Save user failed: ${err.message}`, true);
      }
    });

    byId("cfg-form").addEventListener("submit", (e) => {
      e.preventDefault();
      saveConfigPayload(
        {
          device_name: byId("c-dev-name").value.trim(),
          relay: {
            mode: byId("c-relay-mode").value,
            relay1_pulse_ms: Number(byId("c-r1-ms").value),
            relay2_pulse_ms: Number(byId("c-r2-ms").value),
            travel_time_ms: Number(byId("c-travel-ms").value),
            relay1_hold_open: byId("c-r1-hold").checked,
            relay1_inverted: byId("c-r1-inv").checked,
            relay2_inverted: byId("c-r2-inv").checked,
          },
          sensor: {
            mode: byId("c-sensor-mode").value,
            sc_blink_timeout_ms: Number(byId("c-sc-blink").value),
            cor_indicates_open: byId("c-cor-open").checked,
            in1_inverted: byId("c-in1-inv").checked,
            in2_inverted: byId("c-in2-inv").checked,
            in3_enabled: byId("c-in3-en").checked,
            in3_pedestrian: byId("c-in3-ped").checked,
            in3_inverted: byId("c-in3-inv").checked,
          },
          reader: {
            wiegand_bits: Number(byId("c-wg-bits").value),
            granted_beep_ms: Number(byId("c-wg-beep-ms").value),
            granted_led_ms: Number(byId("c-wg-led-ms").value),
            denied_beeps: Number(byId("c-wg-denied").value),
            pin_timeout_ms: Number(byId("c-pin-to").value),
            keypad_enabled: byId("c-keypad-en").checked,
            led_active_low: byId("c-led-low").checked,
            beep_active_low: byId("c-beep-low").checked,
          },
        },
        "Gate & reader settings saved"
      );
    });

    byId("net-form").addEventListener("submit", (e) => {
      e.preventDefault();
      saveConfigPayload(
        {
          wifi: {
            ssid: byId("c-wifi-ssid").value.trim(),
            password: byId("c-wifi-pass").value,
            hostname: byId("c-wifi-host").value.trim(),
          },
          mqtt: {
            enabled: byId("c-mqtt-en").checked,
            host: byId("c-mqtt-host").value.trim(),
            port: Number(byId("c-mqtt-port").value || 1883),
            username: byId("c-mqtt-user").value.trim(),
            password: byId("c-mqtt-pass").value,
            base_topic: byId("c-mqtt-topic").value.trim(),
            discovery_prefix: byId("c-mqtt-ha-pfx").value.trim(),
            ha_discovery: byId("c-mqtt-ha").checked,
          },
        },
        "Network settings saved"
      );
    });

    byId("btn-reboot").addEventListener("click", () => sendAction("reboot"));
    byId("btn-factory-reset").addEventListener("click", () => {
      if (confirm("Erase all users and settings?")) sendAction("factory_reset");
    });

    function setOtaFile(file) {
      const drop = byId("ota-drop");
      const btn = byId("btn-ota-upload");
      if (!file) {
        drop.classList.remove("has-file");
        byId("ota-file-name").innerHTML = "Drop <code>firmware.bin</code> here or click to browse";
        byId("ota-file-meta").textContent = "Accepts compiled ESP32-C6 .bin image";
        btn.disabled = true;
        return;
      }
      drop.classList.add("has-file");
      byId("ota-file-name").textContent = file.name;
      byId("ota-file-meta").textContent = `${(file.size / 1024).toFixed(1)} KB ready to flash`;
      btn.disabled = false;
    }

    const otaInput = byId("ota-file");
    const otaDrop = byId("ota-drop");
    otaInput.addEventListener("change", () => setOtaFile(otaInput.files[0]));
    otaDrop.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      otaDrop.classList.add("drag");
    });
    otaDrop.addEventListener("dragleave", () => otaDrop.classList.remove("drag"));
    otaDrop.addEventListener("drop", (ev) => {
      ev.preventDefault();
      otaDrop.classList.remove("drag");
      const f = ev.dataTransfer && ev.dataTransfer.files[0];
      if (!f) return;
      const dt = new DataTransfer();
      dt.items.add(f);
      otaInput.files = dt.files;
      setOtaFile(f);
    });

    byId("btn-ota-upload").addEventListener("click", () => {
      const file = otaInput.files[0];
      if (!file) return notify("Select a .bin file first", true);
      const wrap = byId("ota-prog-wrap");
      const prog = byId("ota-prog");
      const pct = byId("ota-prog-pct");
      const btn = byId("btn-ota-upload");
      wrap.classList.remove("hidden");
      btn.disabled = true;
      btn.textContent = "Flashing...";
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/ota");
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          const v = Math.round((ev.loaded / ev.total) * 100);
          prog.value = v;
          pct.textContent = `${v}%`;
        }
      };
      xhr.onload = () => {
        btn.textContent = "Upload & Flash";
        if (xhr.status === 200) notify("OTA complete, rebooting...");
        else {
          btn.disabled = false;
          notify(`OTA failed (${xhr.status})`, true);
        }
      };
      xhr.onerror = () => {
        btn.disabled = false;
        btn.textContent = "Upload & Flash";
        notify("OTA upload error", true);
      };
      xhr.send(file);
    });
  }

  renderScenarioCards();
  bindEvents();
  loadStatus();
  loadEvents();
  setInterval(() => {
    loadStatus();
    if (state.activeTab === "overview") loadEvents();
  }, 2000);
})();
