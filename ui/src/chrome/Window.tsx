import { ReactNode } from 'react';

export function Window({ children, screenLabel }: { children: ReactNode; screenLabel: string }) {
  return (
    <div className="stage">
      <div className="window chrome-macos" data-screen-label={screenLabel}>
        <div className="titlebar">
          <div className="tl">
            <span className="dot r" /><span className="dot y" /><span className="dot g" />
          </div>
          <div className="titlebar-title">LocalScribe</div>
        </div>
        <div className="app">{children}</div>
      </div>
    </div>
  );
}
