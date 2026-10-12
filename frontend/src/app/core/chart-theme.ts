/**
 * Chart.js defaults for every chart (spec 004, T046). No screen sets dataset
 * colours, so these are the whole palette: the design system's indigo, rounded
 * bars, smooth lines and an eased entrance. Chart.js honours
 * `prefers-reduced-motion` on its own only partly, so the animation is short.
 */
export const CHART_DEFAULTS = {
  aspectRatio: 2.2,
  font: { family: 'Inter, Roboto, sans-serif', size: 12 },
  color: '#5b6475',
  borderColor: '#4f46e5',
  backgroundColor: 'rgba(99, 102, 241, 0.78)',
  plugins: {
    // The built-in Colors plugin would override the palette above.
    colors: { enabled: false },
    tooltip: {
      backgroundColor: '#0b1020',
      padding: 10,
      cornerRadius: 8,
      titleFont: { weight: 'bold' },
    },
  },
  datasets: {
    bar: { maxBarThickness: 44 },
    // A soft area under each line; a gap day stays a visible break (spanGaps off).
    line: { fill: 'origin', backgroundColor: 'rgba(99, 102, 241, 0.1)' },
  },
  elements: {
    bar: { borderRadius: 8, borderSkipped: false, hoverBackgroundColor: '#7c3aed' },
    line: { tension: 0.35, borderWidth: 3, borderColor: '#4f46e5' },
    point: { radius: 3, hoverRadius: 6, backgroundColor: '#4f46e5' },
  },
  scale: { grid: { color: 'rgba(148, 163, 184, 0.18)' }, border: { display: false } },
  animation: { duration: 900, easing: 'easeOutQuart' },
} as const;
