import { Icon } from '../primitives/Icon';
import { Waveform } from './Waveform';
import type { AudioDeviceDto } from '../api/types';

interface Props {
  devices: AudioDeviceDto[];
  active: boolean;
  paused?: boolean;
  elapsed: number; // seconds
  outputPath: string;
  selectedDevice: string | null;
  onSelectDevice: (id: string | null) => void;
  onStart: () => void;
  onStop: () => void;
  onPause?: () => void;
  onDiscard?: () => void;
}

export function RecordScreen({
  devices, active, paused = false, elapsed,
  outputPath, selectedDevice, onSelectDevice,
  onStart, onStop, onPause, onDiscard,
}: Props) {
  const mm = Math.floor(elapsed / 60).toString().padStart(2, '0');
  const ss = Math.floor(elapsed % 60).toString().padStart(2, '0');
  const ms = Math.floor((elapsed % 1) * 10);

  const statusClass = !active ? 'idle' : paused ? 'paused' : '';
  const statusLabel = !active ? 'Ready' : paused ? 'Paused' : 'Recording';

  return (
    <div className="record">
      <div className="device-bar">
        <span className="lbl">Input</span>
        <select
          value={selectedDevice ?? ''}
          onChange={(e) => onSelectDevice(e.target.value || null)}
        >
          {devices.length === 0 && <option value="">No devices</option>}
          {devices.map(d => (
            <option key={d.index} value={d.name}>{d.name}</option>
          ))}
        </select>
        <span style={{ color: 'var(--ink-faint)' }}>·</span>
        <span style={{ color: 'var(--ink-dim)' }}>16 kHz · mono</span>
      </div>

      <div className="scribe-canvas">
        <Waveform recording={active && !paused} />
        <div className="time-marks">
          <span>−60s</span><span>−45s</span><span>−30s</span><span>−15s</span><span>now</span>
        </div>
      </div>

      <div className={'timer ' + statusClass}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
          <div className="label">{statusLabel}</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="big">{mm}:{ss}</span>
            <span className="ms">.{ms}</span>
          </div>
        </div>
      </div>

      <div className="record-controls">
        <button className="btn-secondary" onClick={onPause} disabled={!active}>
          <Icon name="pause" size={13} /> {paused ? 'Resume' : 'Pause'}
        </button>
        <button
          className={'btn-record' + (active ? ' is-recording' : '')}
          onClick={() => active ? onStop() : onStart()}
          title={active ? 'Stop' : 'Start recording'}
        >
          <span className="inner" />
        </button>
        <button className="btn-secondary danger" onClick={onDiscard} disabled={!active && elapsed === 0}>
          Discard
        </button>
      </div>

      <div className="privacy-note">
        <Icon name="lock" size={11} stroke={1.4} />
        Audio is captured to disk · <code style={{ fontFamily: 'var(--mono)', color: 'var(--ink-muted)' }}>{outputPath}</code> · never sent over the network.
      </div>
    </div>
  );
}
