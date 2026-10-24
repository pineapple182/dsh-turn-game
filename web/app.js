/* game-lab · 五子棋前端
 * 三个通道共用同一份服务端状态：
 *   点击棋盘  -> POST /api/move
 *   指令输入  -> POST /api/command
 *   SSE 推送  -> GET  /api/stream（断线时降级为轮询）
 */

const $ = (selector) => document.querySelector(selector);

const SIDES = {
  black: { name: "黑方", value: 1, className: "black", glyph: "●" },
  white: { name: "白方", value: 2, className: "white", glyph: "○" },
};

const STAR_POINTS = [
  [3, 3],
  [11, 3],
  [3, 11],
  [11, 11],
  [7, 7],
];

// `?static=1` renders one snapshot without opening the SSE stream; handy for
// headless screenshots, where an endless stream would stall the capture.
const STATIC_MODE = new URLSearchParams(window.location.search).has("static");

const els = {
  connBadge: $("#connBadge"),
  connText: $("#connText"),
  revision: $("#revision"),
  turnStone: $("#turnStone"),
  turnLabel: $("#turnLabel"),
  turnSub: $("#turnSub"),
  lastMove: $("#lastMove"),
  lastMoveText: $("#lastMoveText"),
  modeTag: $("#modeTag"),
  agentModeBtn: $("#agentModeBtn"),
  leaveModeBtn: $("#leaveModeBtn"),
  moveCount: $("#moveCount"),
  undoBtn: $("#undoBtn"),
  resetBtn: $("#resetBtn"),
  overlayReset: $("#overlayReset"),
  resultOverlay: $("#resultOverlay"),
  resultTitle: $("#resultTitle"),
  resultSub: $("#resultSub"),
  log: $("#log"),
  commandForm: $("#commandForm"),
  commandInput: $("#commandInput"),
  jsonView: $("#jsonView"),
  jsonMeta: $("#jsonMeta"),
  toast: $("#toast"),
  copyJsonBtn: $("#copyJsonBtn"),
  downloadJsonBtn: $("#downloadJsonBtn"),
  copyStateBtn: $("#copyStateBtn"),
};

let state = null;
let commandHistory = [];
let historyIndex = 0;
let pollTimer = 0;

/* ------------------------------------------------------------------ canvas */

const easeOutBack = (t) => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};

class BoardView {
  constructor(canvas, { onPlace }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onPlace = onPlace;
    this.state = null;
    this.hover = null;
    this.myTurn = true;
    this.metrics = null;
    this.cssSize = 0;
    this.dpr = 1;
    this.placeAnim = null;
    this.winAnimAt = 0;
    this.raf = 0;
    this._bindEvents();
    this._observeResize();
  }

  _bindEvents() {
    this.canvas.addEventListener("pointermove", (event) => {
      const cell = this._cellFromEvent(event);
      const changed =
        (cell?.x ?? null) !== (this.hover?.x ?? null) || (cell?.y ?? null) !== (this.hover?.y ?? null);
      if (changed) {
        this.hover = cell;
        this.requestDraw();
      }
    });
    this.canvas.addEventListener("pointerleave", () => {
      this.hover = null;
      this.requestDraw();
    });
    this.canvas.addEventListener("click", (event) => {
      if (!this.myTurn) return;
      const cell = this._cellFromEvent(event);
      if (cell) this.onPlace(cell.x, cell.y);
    });
  }

  _observeResize() {
    if (typeof ResizeObserver !== "undefined") {
      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(this.canvas.parentElement);
    }
    window.addEventListener("resize", () => this.resize());
    this.resize();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const cssSize = Math.round(rect.width || 0);
    if (!cssSize) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    if (cssSize === this.cssSize && dpr === this.dpr) return;
    this.cssSize = cssSize;
    this.dpr = dpr;
    this.canvas.width = Math.round(cssSize * dpr);
    this.canvas.height = Math.round(cssSize * dpr);
    this._recomputeMetrics();
    this.draw(performance.now());
  }

  _recomputeMetrics() {
    const size = this.cssSize || this.canvas.getBoundingClientRect().width || 600;
    const n = this.state?.boardSize ?? 15;
    const pad = Math.max(24, size * 0.068);
    const cell = (size - pad * 2) / (n - 1);
    this.metrics = { n, pad, cell, stone: cell * 0.44, size };
  }

  setState(next, { animate = true } = {}) {
    const previous = this.state;
    this.state = next;
    if (!this.metrics || this.metrics.n !== (next?.boardSize ?? 15)) this._recomputeMetrics();

    if (
      animate &&
      next &&
      previous &&
      next.moveCount > (previous.moveCount ?? 0) &&
      next.lastMove
    ) {
      this.placeAnim = { x: next.lastMove.x, y: next.lastMove.y, start: performance.now() };
    } else {
      this.placeAnim = null;
    }

    if (next && next.status !== "playing" && (!previous || previous.status !== next.status)) {
      this.winAnimAt = performance.now();
    }

    this.requestDraw();
    if (this._needsAnimation(performance.now())) this._loop();
  }

  _needsAnimation(now) {
    if (this.placeAnim && now - this.placeAnim.start < 240) return true;
    if (this.state?.winLine && this.state.status !== "playing" && now - this.winAnimAt < 650) return true;
    return false;
  }

  _loop() {
    if (this.raf) return;
    const frame = (now) => {
      this.raf = 0;
      this.draw(now);
      if (this._needsAnimation(now)) this.raf = requestAnimationFrame(frame);
    };
    this.raf = requestAnimationFrame(frame);
  }

  requestDraw() {
    this.draw(performance.now());
  }

  _cellFromEvent(event) {
    if (!this.metrics) return null;
    const rect = this.canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const { pad, cell, n } = this.metrics;
    const gx = Math.round((px - pad) / cell);
    const gy = Math.round((py - pad) / cell);
    if (gx < 0 || gy < 0 || gx >= n || gy >= n) return null;
    const dx = px - (pad + gx * cell);
    const dy = py - (pad + gy * cell);
    if (Math.hypot(dx, dy) > cell * 0.64) return null;
    return { x: gx, y: gy };
  }

  /* ------------------------------------------------------------ drawing */

  draw(now = performance.now()) {
    if (!this.metrics) this._recomputeMetrics();
    const ctx = this.ctx;
    const size = this.metrics?.size ?? this.cssSize;
    if (!size) return;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    this._drawSurface(ctx, size);
    this._drawGrid(ctx);
    this._drawWinTrail(ctx, now);
    this._drawStones(ctx, now);
    this._drawWinRings(ctx, now);
    this._drawLastMarker(ctx);
    this._drawHover(ctx);
  }

  _drawSurface(ctx, size) {
    const grain = ctx.createLinearGradient(0, 0, size, size);
    grain.addColorStop(0, "#e8c07d");
    grain.addColorStop(0.48, "#dcb069");
    grain.addColorStop(1, "#c9964a");
    ctx.fillStyle = grain;
    ctx.fillRect(0, 0, size, size);

    ctx.save();
    ctx.globalAlpha = 0.055;
    ctx.strokeStyle = "#5c3a12";
    ctx.lineWidth = 1;
    for (let i = 0; i < 30; i++) {
      const y = (i / 30) * size + Math.sin(i * 1.7) * 5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.bezierCurveTo(
        size * 0.32,
        y + Math.sin(i) * 7,
        size * 0.68,
        y - Math.cos(i * 1.3) * 7,
        size,
        y + Math.sin(i * 2) * 4,
      );
      ctx.stroke();
    }
    ctx.restore();

    const vignette = ctx.createRadialGradient(size / 2, size / 2, size * 0.22, size / 2, size / 2, size * 0.78);
    vignette.addColorStop(0, "rgba(0,0,0,0)");
    vignette.addColorStop(1, "rgba(64,38,6,0.24)");
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, size, size);
  }

  _drawGrid(ctx) {
    const { pad, cell, n, size } = this.metrics;
    const end = pad + (n - 1) * cell;
    ctx.save();
    ctx.strokeStyle = "rgba(62, 40, 14, 0.62)";
    ctx.lineWidth = Math.max(1, size * 0.0012);
    for (let i = 0; i < n; i++) {
      const p = pad + i * cell;
      ctx.beginPath();
      ctx.moveTo(pad, p);
      ctx.lineTo(end, p);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(p, pad);
      ctx.lineTo(p, end);
      ctx.stroke();
    }

    ctx.strokeStyle = "rgba(56, 34, 10, 0.85)";
    ctx.lineWidth = Math.max(1.5, size * 0.0026);
    ctx.strokeRect(pad, pad, end - pad, end - pad);

    ctx.fillStyle = "rgba(52, 31, 8, 0.78)";
    const dotRadius = Math.max(2, cell * 0.1);
    for (const [sx, sy] of STAR_POINTS) {
      if (sx >= n || sy >= n) continue;
      ctx.beginPath();
      ctx.arc(pad + sx * cell, pad + sy * cell, dotRadius, 0, Math.PI * 2);
      ctx.fill();
    }

    const fontPx = Math.max(9, Math.min(12, cell * 0.32));
    ctx.font = `600 ${fontPx}px "Segoe UI", "Microsoft YaHei", sans-serif`;
    ctx.fillStyle = "rgba(66, 42, 12, 0.78)";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const labelY = end + (size - end) / 2;
    const labelX = pad / 2;
    for (let i = 0; i < n; i++) {
      const letter = String.fromCharCode(65 + i);
      ctx.fillText(letter, pad + i * cell, labelY);
      ctx.fillText(String(n - i), labelX, pad + i * cell);
    }
    ctx.restore();
  }

  _drawStone(ctx, cx, cy, value, scale = 1, alpha = 1) {
    const r = this.metrics.stone * scale;
    if (r <= 0) return;
    const isBlack = value === 1;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.shadowColor = "rgba(0, 0, 0, 0.38)";
    ctx.shadowBlur = r * 0.6;
    ctx.shadowOffsetY = r * 0.16;

    const gradient = ctx.createRadialGradient(cx - r * 0.34, cy - r * 0.4, r * 0.12, cx, cy, r);
    if (isBlack) {
      gradient.addColorStop(0, "#656a72");
      gradient.addColorStop(0.42, "#24272d");
      gradient.addColorStop(1, "#04050a");
    } else {
      gradient.addColorStop(0, "#ffffff");
      gradient.addColorStop(0.6, "#f1efe8");
      gradient.addColorStop(1, "#c9c3b3");
    }
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.shadowColor = "transparent";
    ctx.lineWidth = Math.max(1, r * 0.07);
    ctx.strokeStyle = isBlack ? "rgba(255, 255, 255, 0.14)" : "rgba(60, 48, 24, 0.3)";
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(cx - r * 0.32, cy - r * 0.38, r * 0.22, 0, Math.PI * 2);
    ctx.fillStyle = isBlack ? "rgba(255, 255, 255, 0.2)" : "rgba(255, 255, 255, 0.92)";
    ctx.fill();
    ctx.restore();
  }

  _drawStones(ctx, now) {
    const board = this.state?.board;
    if (!board) return;
    const { pad, cell, n } = this.metrics;
    for (let gy = 0; gy < n; gy++) {
      for (let gx = 0; gx < n; gx++) {
        const value = board[gy]?.[gx];
        if (!value) continue;
        let scale = 1;
        if (this.placeAnim && this.placeAnim.x === gx && this.placeAnim.y === gy) {
          const t = Math.min(1, (now - this.placeAnim.start) / 200);
          scale = 0.55 + 0.45 * easeOutBack(t);
          if (t >= 1) this.placeAnim = null;
        }
        this._drawStone(ctx, pad + gx * cell, pad + gy * cell, value, scale);
      }
    }
  }

  _drawLastMarker(ctx) {
    const last = this.state?.lastMove;
    if (!last) return;
    const { pad, cell, stone } = this.metrics;
    const cx = pad + last.x * cell;
    const cy = pad + last.y * cell;
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, Math.max(2.2, stone * 0.24), 0, Math.PI * 2);
    ctx.fillStyle = "rgba(214, 74, 54, 0.92)";
    ctx.fill();
    ctx.lineWidth = 1.4;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
    ctx.stroke();
    ctx.restore();
  }

  _winProgress(now) {
    const line = this.state?.winLine;
    if (!line || line.length < 2) return null;
    const t = this.state.status === "playing" ? 0 : Math.min(1, (now - this.winAnimAt) / 600);
    return 1 - Math.pow(1 - t, 3);
  }

  _drawWinTrail(ctx, now) {
    const line = this.state?.winLine;
    const eased = this._winProgress(now);
    if (!line || eased === null || eased <= 0) return;
    const { pad, cell, stone } = this.metrics;
    const start = line[0];
    const end = line[line.length - 1];
    const x1 = pad + start.x * cell;
    const y1 = pad + start.y * cell;
    const x2 = pad + end.x * cell;
    const y2 = pad + end.y * cell;

    ctx.save();
    ctx.globalAlpha = eased;

    // Soft halo behind each winning stone, so the run reads even on the wood.
    for (const point of line) {
      const cx = pad + point.x * cell;
      const cy = pad + point.y * cell;
      const halo = ctx.createRadialGradient(cx, cy, stone * 0.55, cx, cy, stone * 1.7);
      halo.addColorStop(0, "rgba(255, 208, 96, 0.7)");
      halo.addColorStop(1, "rgba(255, 208, 96, 0)");
      ctx.beginPath();
      ctx.arc(cx, cy, stone * 1.7, 0, Math.PI * 2);
      ctx.fillStyle = halo;
      ctx.fill();
    }

    // Dark under-stroke keeps the gold readable against the wooden board.
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(52, 30, 4, 0.45)";
    ctx.lineWidth = Math.max(6, cell * 0.42);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x1 + (x2 - x1) * eased, y1 + (y2 - y1) * eased);
    ctx.stroke();

    ctx.strokeStyle = "rgba(255, 193, 74, 0.95)";
    ctx.lineWidth = Math.max(4, cell * 0.26);
    ctx.shadowColor = "rgba(255, 176, 40, 0.95)";
    ctx.shadowBlur = 16;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x1 + (x2 - x1) * eased, y1 + (y2 - y1) * eased);
    ctx.stroke();
    ctx.restore();
  }

  _drawWinRings(ctx, now) {
    const line = this.state?.winLine;
    const eased = this._winProgress(now);
    if (!line || eased === null || eased <= 0) return;
    const { pad, cell, stone } = this.metrics;
    ctx.save();
    ctx.globalAlpha = eased;
    for (const point of line) {
      const cx = pad + point.x * cell;
      const cy = pad + point.y * cell;
      ctx.beginPath();
      ctx.arc(cx, cy, stone * 1.1, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(52, 30, 4, 0.5)";
      ctx.lineWidth = Math.max(3.5, cell * 0.09);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, stone * 1.08, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255, 205, 110, 0.98)";
      ctx.lineWidth = Math.max(2, cell * 0.055);
      ctx.shadowColor = "rgba(255, 190, 70, 0.9)";
      ctx.shadowBlur = 8;
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawHover(ctx) {
    if (!this.myTurn) return;
    if (!this.state || this.state.status !== "playing" || !this.state.currentPlayer) return;
    const hover = this.hover;
    if (!hover) return;
    if (this.state.board[hover.y]?.[hover.x] !== 0) return;
    const { pad, cell } = this.metrics;
    const value = this.state.currentPlayer === "white" ? 2 : 1;
    this._drawStone(ctx, pad + hover.x * cell, pad + hover.y * cell, value, 0.96, 0.36);
  }
}

/* --------------------------------------------------------------- networking */

async function fetchState() {
  const response = await fetch("/api/state", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { status: response.status, ok: response.ok, body };
}

function applyState(next) {
  if (!next || typeof next.revision !== "number") return;
  if (state && next.revision < state.revision) return;
  if (state && next.revision === state.revision) return;
  state = next;
  window.__gamelabState = state; // debugging hook (read-only in practice)
  render();
}

function displayName(sideName) {
  if (!state?.mode) return SIDES[sideName].name;
  return sideName === state.mode.agentSide ? "大肥鱼" : "你";
}

function isHumanTurn() {
  if (!state || state.status !== "playing") return false;
  if (!state.mode) return true;
  return state.currentPlayer === state.mode.humanSide;
}

function render() {
  if (!state) return;
  const side = state.currentPlayer ? SIDES[state.currentPlayer] : null;
  const winner = state.winner ? SIDES[state.winner] : null;
  const mode = state.mode;
  const thinking = Boolean(mode && state.agentThinking);

  els.revision.textContent = String(state.revision);
  els.moveCount.textContent = `${state.moveCount} 手`;
  els.undoBtn.disabled = state.moveCount === 0 || Boolean(mode);
  els.undoBtn.title = mode ? "人机对局暂不支持悔棋" : "悔棋（快捷键 U）";

  els.turnStone.className = "turn-stone";
  if (state.status === "playing" && side) {
    els.turnStone.classList.add(side.className);
    if (mode) {
      const human = SIDES[mode.humanSide];
      const agent = SIDES[mode.agentSide];
      if (state.currentPlayer === mode.humanSide) {
        els.turnLabel.textContent = `${human.name}行棋`;
        els.turnSub.textContent = `轮到你 · 第 ${state.moveCount + 1} 手`;
      } else {
        els.turnStone.classList.add("thinking");
        els.turnLabel.textContent = `${agent.name}行棋`;
        els.turnSub.textContent = thinking ? "大肥鱼思考中…" : "等待大肥鱼落子…";
      }
    } else {
      els.turnLabel.textContent = `${side.name}行棋`;
      els.turnSub.textContent = `第 ${state.moveCount + 1} 手 · 点击棋盘落子`;
    }
  } else if (winner) {
    els.turnStone.classList.add(winner.className, "win");
    els.turnLabel.textContent = `${displayName(state.winner)}获胜`;
    els.turnSub.textContent = mode ? "人机对战 · 点击「新开一局」继续" : "五子连珠 · 点击「新开一局」继续";
  } else {
    els.turnLabel.textContent = "和棋";
    els.turnSub.textContent = mode ? "人机对战 · 棋盘已下满" : "棋盘已下满 · 点击「新开一局」继续";
  }

  els.modeTag.hidden = !mode;
  els.agentModeBtn.hidden = Boolean(mode);
  els.leaveModeBtn.hidden = !mode;
  if (mode) {
    els.modeTag.textContent = `人机对战 · 你执 ${SIDES[mode.humanSide].glyph} · 大肥鱼执 ${SIDES[mode.agentSide].glyph}`;
  }

  if (state.lastMove) {
    els.lastMove.hidden = false;
    els.lastMoveText.textContent = state.lastMove.notation;
  } else {
    els.lastMove.hidden = true;
  }

  const finished = state.status !== "playing";
  els.resultOverlay.hidden = !finished;
  if (finished) {
    els.resultTitle.textContent = winner ? `${displayName(state.winner)}获胜` : "和棋";
    els.resultSub.textContent = winner
      ? (mode ? "人机对战 · 五子连珠" : "五子连珠，漂亮的一局")
      : (mode ? "人机对战 · 棋盘已下满" : "225 手全部下满，势均力敌");
  }

  els.jsonMeta.textContent = `schemaVersion ${state.schemaVersion} · rev ${state.revision}`;
  renderJson(state);
  view.myTurn = isHumanTurn();
  view.canvas.style.cursor = view.myTurn ? "crosshair" : "not-allowed";
  view.setState(state, { animate: !STATIC_MODE });
  if (STATIC_MODE) {
    // Jump to the end of the win animation: headless captures may never run
    // the rAF loop long enough for the fade to finish.
    view.winAnimAt = -1e9;
    view.requestDraw();
  }
}

function renderJson(value) {
  els.jsonView.innerHTML = highlightJson(formatJson(value));
}

/* Pretty-printer tuned for game state: primitive arrays (board rows) and flat
 * objects (rules, moves) stay on one line so the board stays scannable. */
function formatJson(value, indent = 0) {
  const pad = "  ".repeat(indent);
  const childPad = "  ".repeat(indent + 1);

  if (value === null || typeof value !== "object") return JSON.stringify(value);

  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const isPrimitive = (item) => item === null || typeof item !== "object";
    if (value.every(isPrimitive)) {
      return `[${value.map((item) => JSON.stringify(item)).join(", ")}]`;
    }
    const isFlatObject = (item) =>
      item !== null &&
      typeof item === "object" &&
      !Array.isArray(item) &&
      Object.values(item).every(isPrimitive);
    if (value.every(isFlatObject)) {
      return `[\n${value.map((item) => `${childPad}${inlineObject(item)}`).join(",\n")}\n${pad}]`;
    }
    return `[\n${value.map((item) => `${childPad}${formatJson(item, indent + 1)}`).join(",\n")}\n${pad}]`;
  }

  const entries = Object.entries(value);
  if (entries.length === 0) return "{}";
  if (entries.every(([, item]) => item === null || typeof item !== "object")) {
    return `{ ${entries.map(([key, item]) => `${JSON.stringify(key)}: ${JSON.stringify(item)}`).join(", ")} }`;
  }
  return `{\n${entries.map(([key, item]) => `${childPad}${JSON.stringify(key)}: ${formatJson(item, indent + 1)}`).join(",\n")}\n${pad}}`;
}

function inlineObject(object) {
  const entries = Object.entries(object);
  return `{ ${entries.map(([key, value]) => `${JSON.stringify(key)}: ${JSON.stringify(value)}`).join(", ")} }`;
}

function escapeHtml(text) {
  return text.replace(/[&<>]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[character]);
}

function highlightJson(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/g,
    (match, stringToken, colon, literal) => {
      if (stringToken) {
        const cls = colon ? "j-key" : "j-str";
        return `<span class="${cls}">${stringToken}</span>${colon ?? ""}`;
      }
      if (literal) {
        return `<span class="${literal === "null" ? "j-null" : "j-bool"}">${literal}</span>`;
      }
      return `<span class="j-num">${match}</span>`;
    },
  );
}

/* ------------------------------------------------------------------- events */

function addLog(kind, message) {
  const entry = document.createElement("div");
  entry.className = `log-entry ${kind}`;
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  const body = document.createElement("span");
  body.className = "msg";
  body.textContent = message;
  entry.append(time, body);
  els.log.append(entry);
  while (els.log.childElementCount > 80) els.log.firstElementChild?.remove();
  els.log.scrollTop = els.log.scrollHeight;
}

let toastTimer = 0;
function showToast(message, kind = "ok") {
  els.toast.textContent = message;
  els.toast.className = `toast show${kind === "error" ? " error" : ""}`;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    els.toast.className = "toast";
  }, 2200);
}

function finishMessage(payload) {
  const next = payload.state;
  if (!next) return "";
  if (next.status === "draw") return " · 和棋";
  if (next.winner) return ` · ${displayName(next.winner)}五子连珠获胜`;
  return "";
}

function describeResult(payload) {
  const { action } = payload;
  if (action === "place") {
    const move = payload.move;
    addLog("ok", `${displayName(move.player)} ${move.notation} 落子${finishMessage(payload)}`);
  } else if (action === "undo") {
    addLog("ok", `悔棋：撤回 ${displayName(payload.undo.player)} 的 ${payload.undo.notation}`);
  } else if (action === "reset") {
    addLog("ok", "新开一局，轮到黑方");
  } else if (action === "state") {
    addLog("ok", `状态已同步（rev ${payload.state.revision}）`);
  } else if (action === "help") {
    addLog("help", payload.help.join("\n"));
  } else {
    addLog("ok", "操作完成");
  }
}

async function sendCommand(raw) {
  const command = raw.trim();
  if (!command) return;
  addLog("in", `› ${command}`);
  commandHistory.push(command);
  if (commandHistory.length > 50) commandHistory.shift();
  historyIndex = commandHistory.length;

  try {
    const payload = { command };
    if (state?.mode) payload.as = "human";
    const { ok, body } = await postJson("/api/command", payload);
    if (!ok || !body?.ok) {
      const message = body?.error?.message ?? "指令失败";
      addLog("err", `✖ ${message}`);
      showToast(message, "error");
      return;
    }
    applyState(body.state);
    describeResult(body);
  } catch (error) {
    addLog("err", `✖ 网络错误：${error.message}`);
    showToast("连不上本地服务", "error");
  }
}

async function placeStone(x, y) {
  if (!state || state.status !== "playing") return;
  if (!isHumanTurn()) {
    showToast("现在是大肥鱼的回合", "error");
    return;
  }
  try {
    const payload = { x, y };
    if (state.mode) payload.as = "human";
    const { ok, body } = await postJson("/api/move", payload);
    if (!ok || !body?.ok) {
      if (body?.error) showToast(body.error.message, "error");
      return;
    }
    applyState(body.state);
    describeResult(body);
  } catch (error) {
    showToast(`落子失败：${error.message}`, "error");
  }
}

async function leaveAgentMode() {
  try {
    const { ok, body } = await postJson("/api/mode", { clear: true });
    if (!ok || !body?.ok) {
      showToast(body?.error?.message ?? "退出失败", "error");
      return;
    }
    applyState(body.state);
    addLog("ok", "已退出人机对战");
    showToast("已退出人机对战");
  } catch (error) {
    showToast(`退出失败：${error.message}`, "error");
  }
}

async function startAgentMode() {
  try {
    await postJson("/api/reset", {});
    const { ok, body } = await postJson("/api/mode", { humanSide: "black", agentSide: "white" });
    if (!ok || !body?.ok) {
      showToast(body?.error?.message ?? "开局失败", "error");
      return;
    }
    applyState(body.state);
    addLog("ok", "已开启人机对战：你执黑，大肥鱼执白");
    showToast("已开启人机对战；在对话里说「绑定棋局」让大肥鱼接上");
  } catch (error) {
    showToast(`开局失败：${error.message}`, "error");
  }
}

/* ------------------------------------------------------------------ start up */

const view = new BoardView(document.getElementById("board"), {
  onPlace: (x, y) => placeStone(x, y),
});

function setConnection(mode, text) {
  els.connBadge.dataset.state = mode;
  els.connText.textContent = text;
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = window.setInterval(async () => {
    try {
      applyState(await fetchState());
    } catch {
      /* keep trying quietly */
    }
  }, 2000);
}

function stopPolling() {
  if (!pollTimer) return;
  window.clearInterval(pollTimer);
  pollTimer = 0;
}

function connectStream() {
  if (typeof EventSource === "undefined") {
    startPolling();
    setConnection("reconnecting", "轮询模式");
    return;
  }
  setConnection("reconnecting", "连接中…");
  const source = new EventSource("/api/stream");
  source.addEventListener("open", () => {
    stopPolling();
    setConnection("online", "实时连接");
  });
  source.addEventListener("state", (event) => {
    stopPolling();
    setConnection("online", "实时连接");
    try {
      applyState(JSON.parse(event.data));
    } catch {
      /* ignore malformed frame */
    }
  });
  source.addEventListener("error", () => {
    setConnection("offline", "重连中…");
    startPolling();
  });
}

async function copyJson() {
  const text = formatJson(state);
  try {
    await navigator.clipboard.writeText(text);
    showToast("JSON 已复制到剪贴板");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    showToast("JSON 已复制到剪贴板");
  }
}

function downloadJson() {
  const text = formatJson(state);
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `gomoku-state-${state?.revision ?? "unknown"}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  showToast("已下载状态 JSON");
}

els.commandForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const command = els.commandInput.value;
  els.commandInput.value = "";
  sendCommand(command);
});

els.commandInput.addEventListener("keydown", (event) => {
  if (event.key === "ArrowUp") {
    if (!commandHistory.length) return;
    event.preventDefault();
    historyIndex = Math.max(0, historyIndex - 1);
    els.commandInput.value = commandHistory[historyIndex] ?? "";
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    historyIndex = Math.min(commandHistory.length, historyIndex + 1);
    els.commandInput.value = commandHistory[historyIndex] ?? "";
  } else if (event.key === "Escape") {
    els.commandInput.blur();
  }
});

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => sendCommand(chip.dataset.command ?? ""));
}

els.undoBtn.addEventListener("click", () => sendCommand("undo"));
els.resetBtn.addEventListener("click", () => sendCommand("reset"));
els.overlayReset.addEventListener("click", () => sendCommand("reset"));
els.agentModeBtn.addEventListener("click", startAgentMode);
els.leaveModeBtn.addEventListener("click", leaveAgentMode);
els.copyJsonBtn.addEventListener("click", () => (state ? copyJson() : undefined));
els.copyStateBtn.addEventListener("click", () => (state ? copyJson() : undefined));
els.downloadJsonBtn.addEventListener("click", () => (state ? downloadJson() : undefined));

window.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLInputElement) return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const key = event.key.toLowerCase();
  if (key === "u") sendCommand("undo");
  else if (key === "r") sendCommand("reset");
  else if (key === "c") els.commandInput.focus();
});

async function boot() {
  if (STATIC_MODE) document.body.classList.add("static-snapshot");
  addLog("help", "指令台就绪：输入 H8 落子，或直接点击棋盘。");  addLog("help", "CLI 也可以：python -m gamelab move H8");
  try {
    applyState(await fetchState());
  } catch {
    setConnection("offline", "服务未连接");
    showToast("连不上本地服务，请先运行 python -m gamelab serve", "error");
  }
  if (STATIC_MODE) {
    setConnection("online", "快照模式");
  } else {
    connectStream();
  }
}

boot();
