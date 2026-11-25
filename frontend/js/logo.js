/** Reusable BraveBank swoosh-star SVG artwork, single BRAVEBANK wordmark, and watermark background layer. */

let uidCounter = 0;

/**
 * Generates the crisp geometric 5-pointed BraveBank star with two dynamic
 * upward-right curved swoosh ribbons matching the approved mockup.
 * @param {"brand"|"splash"|"watermark"} variant
 * @param {string} className
 */
export function brandStarSvg(variant = "brand", className = "bb-star-svg") {
  uidCounter += 1;
  const uid = `bbstar_${variant}_${uidCounter}`;
  const isSplash = variant === "splash";
  const isWatermark = variant === "watermark";

  const starColors = isSplash
    ? `<linearGradient id="${uid}_a" x1="16" y1="10" x2="104" y2="108" gradientUnits="userSpaceOnUse">
         <stop offset="0%" stop-color="#FFFFFF"/>
         <stop offset="55%" stop-color="#E2EEFF"/>
         <stop offset="100%" stop-color="#6EB5FF"/>
       </linearGradient>
       <linearGradient id="${uid}_b" x1="60" y1="14" x2="108" y2="104" gradientUnits="userSpaceOnUse">
         <stop offset="0%" stop-color="#DCEBFF"/>
         <stop offset="100%" stop-color="#3390FF"/>
       </linearGradient>`
    : isWatermark
      ? `<linearGradient id="${uid}_a" x1="10" y1="10" x2="110" y2="110" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#DCEAFF"/>
           <stop offset="100%" stop-color="#CFE1FF"/>
         </linearGradient>
         <linearGradient id="${uid}_b" x1="60" y1="10" x2="110" y2="110" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#D4E5FF"/>
           <stop offset="100%" stop-color="#C3DAFF"/>
         </linearGradient>`
      : `<linearGradient id="${uid}_a" x1="16" y1="12" x2="96" y2="96" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#38B6FF"/>
           <stop offset="50%" stop-color="#007BFF"/>
           <stop offset="100%" stop-color="#0044BD"/>
         </linearGradient>
         <linearGradient id="${uid}_b" x1="60" y1="16" x2="106" y2="102" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#0066E6"/>
           <stop offset="100%" stop-color="#002E8A"/>
         </linearGradient>`;

  return `
    <svg class="${className}" viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <defs>
        ${starColors}
        <mask id="${uid}_mask">
          <rect width="120" height="120" fill="white"/>
          <path d="M12 95 Q52 50 112 45 Q64 58 28 104 Z" fill="black"/>
          <path d="M18 82 Q55 41 112 42 Q61 48 24 88 Z" fill="black"/>
        </mask>
      </defs>
      <g mask="url(#${uid}_mask)">
        <path d="M60 8L74.8 39.2L109.5 43.8L84.2 67.6L90.6 101.8L60 85.2L29.4 101.8L35.8 67.6L10.5 43.8L45.2 39.2L60 8Z" fill="url(#${uid}_a)"/>
        <path d="M60 8L74.8 39.2L109.5 43.8L84.2 67.6L90.6 101.8L60 85.2V8Z" fill="url(#${uid}_b)" opacity="0.78"/>
        ${isWatermark ? "" : `<path d="M60 8L74.8 39.2L60 54L45.2 39.2L60 8Z" fill="${isSplash ? "#FFFFFF" : "#6AC8FF"}" opacity="0.65"/>`}
      </g>
    </svg>
  `;
}

/**
 * Renders the single complete BRAVEBANK brand lockup (never duplicated or split across two headings).
 * @param {object} opts
 * @param {"splash"|"hero"|"compact"|"sidebar"} [opts.size="compact"]
 * @param {boolean} [opts.showTagline=true]
 * @param {boolean} [opts.showArc=false]
 */
export function renderBrandLockup({
  size = "compact",
  showTagline = true,
  showArc = false,
} = {}) {
  const isSplash = size === "splash";
  const starVariant = isSplash ? "splash" : "brand";
  const starClass =
    size === "splash"
      ? "splash-star-core"
      : size === "hero"
        ? "brand-star-emblem"
        : "brand-star-sm";

  return `
    <div class="bb-lockup bb-lockup-${size}">
      ${brandStarSvg(starVariant, starClass)}
      <div class="bb-wordmark" aria-label="BRAVEBANK">
        <span class="bb-word-brave">BRAVE</span><span class="bb-word-bank">BANK</span>
      </div>
      ${showTagline ? `<p class="bb-tagline">Banking Without Limits</p>` : ""}
      ${
        showArc
          ? `<svg class="bb-tagline-arc" viewBox="0 0 180 14" fill="none" aria-hidden="true">
               <path d="M18 11 C 62 2, 118 2, 162 10" stroke="#007BFF" stroke-width="2.4" stroke-linecap="round"/>
             </svg>`
          : ""
      }
    </div>
  `;
}

/**
 * Reusable subtle pale-blue star watermark background placed safely behind content.
 */
export function renderWatermarkLayer(variant = "light") {
  const starClass = variant === "splash" ? "watermark-star-splash" : "watermark-star-light";
  const starMode = variant === "splash" ? "splash" : "watermark";
  return `
    <div class="bb-watermark-layer bb-watermark-${variant}" aria-hidden="true">
      ${brandStarSvg(starMode, `${starClass} wm-top-right`)}
      ${brandStarSvg(starMode, `${starClass} wm-mid-left`)}
    </div>
  `;
}

/** Hydrates all declarative [data-bb-brand] and [data-bb-watermark] slots in the DOM. */
export function hydrateBrandElements() {
  document.querySelectorAll("[data-bb-brand]").forEach((el) => {
    const size = el.dataset.bbBrand || "compact";
    const showTagline = el.dataset.bbTagline !== "false";
    const showArc = el.dataset.bbArc === "true";
    el.innerHTML = renderBrandLockup({ size, showTagline, showArc });
  });

  document.querySelectorAll("[data-bb-watermark]").forEach((el) => {
    const variant = el.dataset.bbWatermark || "light";
    el.innerHTML = renderWatermarkLayer(variant);
  });
}
