/** Reusable BraveBank swoosh-star SVG artwork, single BRAVEBANK wordmark, and watermark background layer. */

let uidCounter = 0;

/**
 * Generates the crisp geometric 5-pointed BraveBank star with faceted blue shading
 * and two curved upward-right swoosh ribbons matching the approved mockup.
 * @param {"brand"|"splash"|"watermark"} variant
 * @param {string} className
 */
export function brandStarSvg(variant = "brand", className = "bb-star-svg") {
  uidCounter += 1;
  const uid = `bbstar_${variant}_${uidCounter}`;
  const isSplash = variant === "splash";
  const isWatermark = variant === "watermark";

  const starColors = isSplash
    ? `<linearGradient id="${uid}_a" x1="12" y1="8" x2="106" y2="108" gradientUnits="userSpaceOnUse">
         <stop offset="0%" stop-color="#FFFFFF"/>
         <stop offset="52%" stop-color="#E5F1FF"/>
         <stop offset="100%" stop-color="#60ADFF"/>
       </linearGradient>
       <linearGradient id="${uid}_b" x1="60" y1="10" x2="108" y2="104" gradientUnits="userSpaceOnUse">
         <stop offset="0%" stop-color="#D4E8FF"/>
         <stop offset="100%" stop-color="#2B88FF"/>
       </linearGradient>`
    : isWatermark
      ? `<linearGradient id="${uid}_a" x1="10" y1="10" x2="110" y2="110" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#DFECFF"/>
           <stop offset="100%" stop-color="#CBE0FF"/>
         </linearGradient>
         <linearGradient id="${uid}_b" x1="60" y1="10" x2="110" y2="110" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#D5E6FF"/>
           <stop offset="100%" stop-color="#BDD6FF"/>
         </linearGradient>`
      : `<linearGradient id="${uid}_a" x1="14" y1="10" x2="96" y2="96" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#4AC3FF"/>
           <stop offset="48%" stop-color="#007BFF"/>
           <stop offset="100%" stop-color="#003EB3"/>
         </linearGradient>
         <linearGradient id="${uid}_b" x1="60" y1="12" x2="108" y2="102" gradientUnits="userSpaceOnUse">
           <stop offset="0%" stop-color="#0068EB"/>
           <stop offset="100%" stop-color="#00287A"/>
         </linearGradient>`;

  return `
    <svg class="${className}" viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <defs>
        ${starColors}
        <mask id="${uid}_mask">
          <rect width="120" height="120" fill="white"/>
          <path d="M10 94 Q49 48 112 43 Q62 56 26 103 Z" fill="black"/>
          <path d="M16 80 Q53 38 111 40 Q59 46 22 86 Z" fill="black"/>
        </mask>
      </defs>
      <g mask="url(#${uid}_mask)">
        <path d="M60 7L75.2 38.8L110.2 43.5L84.6 67.8L91.2 102.4L60 85.6L28.8 102.4L35.4 67.8L9.8 43.5L44.8 38.8L60 7Z" fill="url(#${uid}_a)"/>
        <path d="M60 7L75.2 38.8L110.2 43.5L84.6 67.8L91.2 102.4L60 85.6V7Z" fill="url(#${uid}_b)" opacity="0.82"/>
        ${isWatermark ? "" : `<path d="M60 7L75.2 38.8L60 53L44.8 38.8L60 7Z" fill="${isSplash ? "#FFFFFF" : "#6ED0FF"}" opacity="0.72"/>`}
        ${isWatermark ? "" : `<path d="M9.8 43.5L44.8 38.8L60 53L35.4 67.8L9.8 43.5Z" fill="${isSplash ? "#FFFFFF" : "#38B6FF"}" opacity="0.35"/>`}
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
               <path d="M14 11 C 60 2, 120 2, 166 10" stroke="#007BFF" stroke-width="2.6" stroke-linecap="round"/>
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
