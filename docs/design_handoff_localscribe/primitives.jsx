// primitives.jsx — icons + small shared bits

const Icon = ({ name, size = 16, stroke = 1.5 }) => {
  const s = { width: size, height: size, fill: 'none', stroke: 'currentColor', strokeWidth: stroke, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'plus':       return <svg viewBox="0 0 16 16" {...s}><path d="M8 3v10M3 8h10"/></svg>;
    case 'transcribe': return <svg viewBox="0 0 16 16" {...s}><path d="M3 4h7M3 8h10M3 12h6"/></svg>;
    case 'mic':        return <svg viewBox="0 0 16 16" {...s}><rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3.5 8a4.5 4.5 0 009 0M8 12.5V14"/></svg>;
    case 'eye':        return <svg viewBox="0 0 16 16" {...s}><path d="M1.5 8C3 4.5 5.5 3 8 3s5 1.5 6.5 5c-1.5 3.5-4 5-6.5 5S3 11.5 1.5 8z"/><circle cx="8" cy="8" r="2"/></svg>;
    case 'folder':     return <svg viewBox="0 0 16 16" {...s}><path d="M2 4.5A1.5 1.5 0 013.5 3h2.8l1.4 1.5h4.8A1.5 1.5 0 0114 6v5.5A1.5 1.5 0 0112.5 13h-9A1.5 1.5 0 012 11.5v-7z"/></svg>;
    case 'book':       return <svg viewBox="0 0 16 16" {...s}><path d="M3 3h4a2 2 0 012 2v8a2 2 0 00-2-2H3V3zM13 3H9a2 2 0 00-2 2v8a2 2 0 012-2h4V3z"/></svg>;
    case 'gear':       return <svg viewBox="0 0 16 16" {...s}><circle cx="8" cy="8" r="2"/><path d="M8 1v2M8 13v2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4M1 8h2M13 8h2M3.5 12.5l1.4-1.4M11.1 4.9l1.4-1.4"/></svg>;
    case 'upload':     return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>;
    case 'chev':       return <svg viewBox="0 0 16 16" {...s}><path d="M6 4l4 4-4 4"/></svg>;
    case 'copy':       return <svg viewBox="0 0 16 16" {...s}><rect x="5" y="5" width="9" height="9" rx="1.5"/><path d="M3 11V3a1 1 0 011-1h7"/></svg>;
    case 'doc':        return <svg viewBox="0 0 16 16" {...s}><path d="M3.5 2h6L13 5.5v8A1.5 1.5 0 0111.5 15h-8A1.5 1.5 0 012 13.5v-10A1.5 1.5 0 013.5 2z"/><path d="M9 2v4h4"/></svg>;
    case 'braces':     return <svg viewBox="0 0 16 16" {...s}><path d="M5.5 2.5C4 2.5 4 4 4 5s0 2.5-2 2.5C4 8 4 9.5 4 10.5s0 2.5 1.5 2.5"/><path d="M10.5 2.5C12 2.5 12 4 12 5s0 2.5 2 2.5c-2 .5-2 2-2 3s0 2.5-1.5 2.5"/></svg>;
    case 'wave':       return <svg viewBox="0 0 16 16" {...s}><path d="M2 8h1M5 5v6M8 3v10M11 5v6M13 8h1"/></svg>;
    case 'shield':     return <svg viewBox="0 0 16 16" {...s}><path d="M8 1.5l5 1.5v4.5c0 3-2 5.5-5 6.5-3-1-5-3.5-5-6.5V3l5-1.5z"/></svg>;
    case 'lock':       return <svg viewBox="0 0 16 16" {...s}><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 015 0v2"/></svg>;
    case 'sparkle':    return <svg viewBox="0 0 16 16" {...s}><path d="M8 2v3M8 11v3M2 8h3M11 8h3M4 4l2 2M10 10l2 2M12 4l-2 2M6 10l-2 2"/></svg>;
    case 'pause':      return <svg viewBox="0 0 16 16" {...s}><rect x="4.5" y="3.5" width="2.5" height="9" rx="0.5"/><rect x="9" y="3.5" width="2.5" height="9" rx="0.5"/></svg>;
    case 'check':      return <svg viewBox="0 0 16 16" {...s}><path d="M3 8.5l3.2 3.2L13 5"/></svg>;
    case 'search':     return <svg viewBox="0 0 16 16" {...s}><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>;
    default:           return null;
  }
};

// Speaker accent palette — muted, paper-friendly
const SPEAKER_COLORS = ['#6fd99a', '#e8b169', '#7aa5e8', '#d97e94', '#c2a3e8'];

Object.assign(window, { Icon, SPEAKER_COLORS });
