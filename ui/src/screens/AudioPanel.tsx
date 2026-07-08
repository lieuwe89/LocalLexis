import { useEffect, useRef, useState } from 'react';
import { apiBlob } from '../api/client';
import { Icon } from '../primitives/Icon';

interface Props {
  tid: string;
  filename: string;
  /** Receives a seek(seconds) function once the player is ready. */
  onReady?: (seek: (secs: number) => void) => void;
}

export function AudioPanel({ tid, filename, onReady }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    apiBlob(`/transcripts/${tid}/audio`)
      .then(blob => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [tid]);

  useEffect(() => {
    if (url && onReady) {
      onReady((secs: number) => {
        const el = audioRef.current;
        if (el) {
          el.currentTime = secs;
          el.play().catch(() => {});
        }
      });
    }
  }, [url, onReady]);

  if (failed) {
    return <div className="audio-panel audio-unavailable">audio unavailable on server</div>;
  }
  if (!url) {
    return <div className="audio-panel">loading audio…</div>;
  }
  return (
    <div className="audio-panel">
      <audio ref={audioRef} aria-label="Transcript audio" controls src={url} preload="metadata" />
      <a className="icon-btn" aria-label="Download audio" title="Download audio"
         href={url} download={filename}>
        <Icon name="download" size={15} />
      </a>
    </div>
  );
}
