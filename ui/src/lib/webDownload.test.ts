import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { webDownloadTranscriptFile } from './webDownload';

describe('webDownloadTranscriptFile', () => {
  const createObjectURL = vi.fn(() => 'blob:fake');
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(Object.create(URL), { createObjectURL, revokeObjectURL }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('fetches the file route and triggers an anchor download', async () => {
    const blob = new Blob(['S1: hoi\n'], { type: 'text/plain' });
    const fetchBlob = vi.fn(async () => blob);
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await webDownloadTranscriptFile(fetchBlob, 'rec 1', 'txt');

    expect(fetchBlob).toHaveBeenCalledWith('/transcripts/rec%201/file/txt');
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake');
    click.mockRestore();
  });

  it('names the download after the transcript id and format', async () => {
    const fetchBlob = vi.fn(async () => new Blob(['{}']));
    let downloadName = '';
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloadName = this.download;
      });

    await webDownloadTranscriptFile(fetchBlob, 'rec', 'json');

    expect(downloadName).toBe('rec.json');
    click.mockRestore();
  });

  it('propagates fetch errors without touching the DOM', async () => {
    const fetchBlob = vi.fn(async () => {
      throw new Error('404 nope');
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await expect(webDownloadTranscriptFile(fetchBlob, 'rec', 'txt')).rejects.toThrow('404 nope');
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    click.mockRestore();
  });
});
