export type JobStatus = 'pending' | 'running' | 'complete' | 'failed';

export interface JobRecord {
  id: string;
  kind: 'transcribe' | 'record';
  status: JobStatus;
  stage: string;
  percent: number;
  error: string | null;
  transcript_id: string | null;
  audio_path: string | null;
  paths: Record<string, string>;
}

export type SseEvent =
  | { type: 'stage'; stage: string; percent: number }
  | { type: 'line'; speaker: string; ts: number; text: string }
  | { type: 'complete'; transcript_id: string; paths: Record<string, string> }
  | { type: 'error'; message: string };

export interface TranscriptListItem {
  id: string;
  path: string;
  audio_path?: string;
  duration_seconds?: number;
  language?: string;
  speakers?: number;
  created_at?: string;
  models?: Record<string, string>;
  error?: string;
  /** HTML snippet from FTS5 (with <mark> tags). Only set on search results. */
  snippet?: string;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  speaker: string;
  text: string;
}

export interface TranscriptDoc {
  version: number;
  audio_path: string;
  duration_seconds: number;
  language: string;
  speakers: Record<string, string>;
  segments: TranscriptSegment[];
  models: Record<string, string>;
  created_at: string;
  paths?: { json?: string; txt?: string };
}

export interface AudioDeviceDto {
  index: number;
  name: string;
  channels: number;
  sample_rate: number;
  default: boolean;
  hint: 'mic' | 'loopback' | 'mic+loopback' | 'unknown';
}

export interface ConfigDto {
  backend: 'auto' | 'cpu' | 'cuda' | 'mps';
  asr_model: string;
  hf_token_set: boolean;
  model_cache_dir: string;
  default_out_dir: string | null;
  watch: { recursive: boolean; debounce_seconds: number; extensions: string[] };
}
