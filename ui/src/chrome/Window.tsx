import { ReactNode } from 'react';

export function Window({ children, screenLabel }: { children: ReactNode; screenLabel: string }) {
  return (
    <div className="stage">
      <div className="window chrome-plain" data-screen-label={screenLabel}>
        <div className="app">{children}</div>
      </div>
    </div>
  );
}
