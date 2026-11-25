/** Lightweight blue-purple starfield backdrop, synthesized Web Audio chime, and falling-petal celebration. */

const SOUND_MUTE_STORAGE_KEY = "bravebank_sound_muted";
const celebratedReferences = new Set();

let sharedAudioCtx = null;
let starfieldInitialized = false;

export function isSoundMuted() {
  try {
    return window.localStorage.getItem(SOUND_MUTE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setSoundMuted(muted) {
  try {
    window.localStorage.setItem(SOUND_MUTE_STORAGE_KEY, muted ? "true" : "false");
  } catch {
    // Ignore storage restriction errors in sandboxed iframes
  }
  window.dispatchEvent(new CustomEvent("bravebank:sound-pref-changed", { detail: { muted } }));
}

export function toggleSoundMuted() {
  const next = !isSoundMuted();
  setSoundMuted(next);
  return next;
}

function getOrCreateAudioContext() {
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return null;
  if (!sharedAudioCtx) {
    sharedAudioCtx = new AudioCtx();
  }
  if (sharedAudioCtx.state === "suspended") {
    sharedAudioCtx.resume().catch(() => {});
  }
  return sharedAudioCtx;
}

export function unlockAudioOnGesture() {
  const unlock = () => {
    try {
      const ctx = getOrCreateAudioContext();
      if (ctx && ctx.state === "suspended") {
        ctx.resume().catch(() => {});
      }
    } catch {
      // Ignore Web Audio restrictions
    }
  };
  window.addEventListener("pointerdown", unlock, { passive: true, once: true });
  window.addEventListener("keydown", unlock, { passive: true, once: true });
}

export function playTransferChime() {
  if (isSoundMuted()) return;
  try {
    const ctx = getOrCreateAudioContext();
    if (!ctx) return;

    const now = ctx.currentTime;
    const notes = [523.25, 659.25, 783.99, 1046.5]; // C5 -> E5 -> G5 -> C6 warm triad

    notes.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const startAt = now + idx * 0.085;
      const duration = idx === notes.length - 1 ? 0.55 : 0.34;

      osc.type = idx === notes.length - 1 ? "triangle" : "sine";
      osc.frequency.setValueAtTime(freq, startAt);

      gain.gain.setValueAtTime(0.0001, startAt);
      gain.gain.exponentialRampToValueAtTime(idx === notes.length - 1 ? 0.1 : 0.08, startAt + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startAt);
      osc.stop(startAt + duration + 0.03);
    });
  } catch {
    // Graceful no-op when audio playback is restricted
  }
}

export function launchFallingFlowers() {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  const existing = document.getElementById("bb-flower-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "bb-flower-overlay";
  overlay.className = "bb-flower-overlay";
  overlay.setAttribute("aria-hidden", "true");

  const colors = ["#3390FF", "#8B5CF6", "#FFFFFF", "#F472B6", "#93C5FD", "#C4B5FD"];
  const petalCount = 22;

  for (let i = 0; i < petalCount; i += 1) {
    const petal = document.createElement("span");
    petal.className = "bb-flower-petal";
    const leftPct = (i * 4.5 + (i % 3) * 1.8) % 98;
    const delayMs = (i % 7) * 85;
    const fallMs = 2100 + (i % 5) * 180;
    const driftPx = (i % 2 === 0 ? 1 : -1) * (18 + (i % 4) * 12);
    const scale = 0.78 + (i % 4) * 0.14;
    const color = colors[i % colors.length];

    petal.style.left = `${leftPct}%`;
    petal.style.setProperty("--fall-delay", `${delayMs}ms`);
    petal.style.setProperty("--fall-duration", `${fallMs}ms`);
    petal.style.setProperty("--petal-drift", `${driftPx}px`);
    petal.style.setProperty("--petal-scale", String(scale));
    petal.innerHTML = `
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
        <path d="M12 2C14.2 5.4 14.5 9.2 12 12C9.5 9.2 9.8 5.4 12 2Z" fill="${color}" opacity="0.92"/>
        <path d="M22 12C18.6 14.2 14.8 14.5 12 12C14.8 9.5 18.6 9.8 22 12Z" fill="${color}" opacity="0.86"/>
        <path d="M12 22C9.8 18.6 9.5 14.8 12 12C14.5 14.8 14.2 18.6 12 22Z" fill="${color}" opacity="0.92"/>
        <path d="M2 12C5.4 9.8 9.2 9.5 12 12C9.2 14.5 5.4 14.2 2 12Z" fill="${color}" opacity="0.86"/>
        <circle cx="12" cy="12" r="2.1" fill="#FDE68A"/>
      </svg>
    `;
    overlay.appendChild(petal);
  }

  document.body.appendChild(overlay);
  window.setTimeout(() => {
    overlay.remove();
  }, 3150);
}

/**
 * Triggers audio chime + falling petals strictly once per unique confirmed internal transfer reference.
 */
export function triggerTransferSuccessCelebration(tx) {
  if (!tx || !tx.reference) return;
  if (celebratedReferences.has(tx.reference)) return;
  celebratedReferences.add(tx.reference);
  playTransferChime();
  launchFallingFlowers();
}

export function initStarfieldBackdrop() {
  if (starfieldInitialized || typeof document === "undefined") return;
  starfieldInitialized = true;

  const existing = document.getElementById("bb-floating-stars");
  if (existing) return;

  const container = document.createElement("div");
  container.id = "bb-floating-stars";
  container.className = "bb-floating-stars";
  container.setAttribute("aria-hidden", "true");

  const stars = [
    { x: 8, y: 14, size: 12, dur: 14, delay: 0, tone: "blue" },
    { x: 22, y: 32, size: 8, dur: 18, delay: -3, tone: "purple" },
    { x: 37, y: 12, size: 10, dur: 16, delay: -6, tone: "white" },
    { x: 52, y: 24, size: 14, dur: 20, delay: -2, tone: "purple" },
    { x: 68, y: 10, size: 9, dur: 15, delay: -7, tone: "blue" },
    { x: 84, y: 22, size: 13, dur: 19, delay: -4, tone: "purple" },
    { x: 92, y: 46, size: 10, dur: 17, delay: -8, tone: "blue" },
    { x: 14, y: 64, size: 11, dur: 21, delay: -5, tone: "purple" },
    { x: 31, y: 78, size: 9, dur: 16, delay: -1, tone: "blue" },
    { x: 48, y: 60, size: 12, dur: 22, delay: -9, tone: "white" },
    { x: 65, y: 76, size: 10, dur: 17, delay: -4, tone: "purple" },
    { x: 79, y: 66, size: 14, dur: 19, delay: -11, tone: "blue" },
    { x: 90, y: 84, size: 9, dur: 15, delay: -2, tone: "white" },
    { x: 6, y: 88, size: 11, dur: 18, delay: -6, tone: "purple" },
  ];

  container.innerHTML = stars
    .map(
      (s) => `
      <span
        class="bb-star-node bb-star-${s.tone}"
        style="left:${s.x}%; top:${s.y}%; --star-size:${s.size}px; --star-dur:${s.dur}s; --star-delay:${s.delay}s;"
      ></span>`
    )
    .join("");

  document.body.prepend(container);
}
