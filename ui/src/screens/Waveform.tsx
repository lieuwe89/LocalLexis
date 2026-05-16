import { useEffect, useState } from 'react';

export function Waveform({ recording }: { recording: boolean }) {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    if (!recording) return;
    let raf: number;
    const tick = () => {
      setPhase(p => (p + 0.05) % 1000);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [recording]);

  const W = 1000;
  const H = 220;
  const bars = 140;
  const rand = (i: number) => {
    const x = Math.sin(i * 12.9898 + phase * 0.7) * 43758.5453;
    return x - Math.floor(x);
  };

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
         style={{ width: '100%', height: '100%', display: 'block', color: 'var(--accent)' }}>
      <line x1={32} y1={H/2} x2={W-32} y2={H/2} stroke="var(--line-strong)" strokeWidth="0.5"/>
      {Array.from({ length: bars }).map((_, i) => {
        const x = 32 + (i / (bars - 1)) * (W - 64);
        const live = recording ? 1 : 0;
        const distFromHead = (bars - 1 - i) / (bars - 1);
        const envelope = 0.25 + 0.75 * Math.pow(1 - distFromHead, 1.6);
        const noise = rand(i) * 0.7 + 0.3;
        const wob = recording ? (0.7 + 0.3 * Math.sin((phase * 8) + i * 0.4)) : 0.55;
        const h = (12 + noise * envelope * wob * 80 * (0.4 + live * 0.6));
        const op = 0.25 + envelope * 0.7;
        const isHead = i >= bars - 3;
        return (
          <line
            key={i} x1={x} y1={H/2 - h/2} x2={x} y2={H/2 + h/2}
            stroke="currentColor"
            strokeOpacity={op * (isHead && recording ? 1.15 : 1)}
            strokeWidth={isHead && recording ? 2 : 1.2}
            strokeLinecap="round"
          />
        );
      })}
      <line x1={W-34} y1={20} x2={W-34} y2={H-20}
            stroke="currentColor"
            strokeOpacity={recording ? 0.5 : 0.15}
            strokeWidth="0.5" strokeDasharray="2 3"/>
    </svg>
  );
}
