// Browser-side "save file" for the web build: fetch a transcript's .txt/.json
// through the authed blob helper, then hand it to the browser as a download.
// The fetcher is injected (like webRelabel's `api`) so tests avoid the network.
export async function webDownloadTranscriptFile(
  fetchBlob: (path: string) => Promise<Blob>,
  tid: string,
  fmt: 'txt' | 'json',
): Promise<void> {
  const blob = await fetchBlob(`/transcripts/${encodeURIComponent(tid)}/file/${fmt}`);
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = `${tid}.${fmt}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
