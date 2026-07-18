# Hub als single source of truth — design

**Datum:** 2026-07-18
**Status:** goedgekeurd door gebruiker
**Context:** laptop is al gejoined aan de hub (v0.10.0 hub-client-mode); nieuwe
opnames routeren al naar de hub en hub-transcripten syncen al terug. Wat
ontbreekt: de bestaande laptop-bibliotheek (19 transcripten, ~100MB audio)
staat alleen lokaal, en semantisch zoeken/Ask (v0.17.0) draait alleen waar
sentence-transformers geïnstalleerd is.

## Doel

1. Eenmalige migratie van de bestaande laptop-bibliotheek naar de hub;
   daarna is de hub single source of truth en de laptop een afgeleide.
2. Offline blijft de laptop bruikbaar; gedrag bij geen verbinding is een
   instelling (lokaal transcriberen vs. wachten op de hub).
3. Semantisch zoeken + Ask op de laptop werken door door te sturen naar de
   hub — geen embeddingmodel op de laptop.

## Besluiten

| Vraag | Keuze | Verworpen |
|---|---|---|
| Originelen na migratie | Archiveren naar bestaande trash, pas ná verificatie van de terugkomende hub-kopie | Laten staan (vereist dedup-weergave) |
| Offline opnames | Settings-toggle `lokaal transcriberen` \| `wachten op hub`; default lokaal | Vast gedrag (gebruiker wil rekenkracht soms sparen) |
| Laptop-RAG | Proxy naar hub (signed), offline nette melding + FTS | Lokale embeddings (470MB/CPU), embedding-delegatie (YAGNI: offline semantisch kan toch niet zonder model) |
| Audio mee-migreren | Ja (100MB totaal; playback op hub-web-UI blijft werken) | JSON-only |

## Onderdelen (bouwvolgorde A → B → D → C)

### A. `POST /transcripts/import` (hub)

- Device-signed (zelfde Ed25519-verificatie als `POST /jobs/upload`;
  hergebruik `verify_*` uit `speechtotext/api/auth.py`).
- Multipart: `transcript` (JSON-doc, compleet incl. speakers/_clocks/
  _history/summary) + `audio` (bestand, optioneel — import zonder audio
  levert een transcript zonder playback).
- Hub schrijft audio naar zijn library-dir, herschrijft `audio_path` in het
  doc naar het hub-pad, schrijft de JSON-sidecar atomisch (tmp+rename,
  zelfde patroon als `_atomic_write_json`), regenereert de .txt, en
  indexeert via `library_db.upsert_path` (chunks → EmbedWorker embedt
  vanzelf).
- Idempotent op transcript-id: bestaat de id al op de hub → 200 met
  `{"imported": false, "reason": "exists"}`; nooit overschrijven.
- Groottelimiet: zelfde `max_upload_bytes` als `/jobs/upload`.

### B. Eenmalige migratie (laptop)

- Settings-kaart "Migreer bibliotheek naar hub" (alleen zichtbaar wanneer
  gejoined), met voortgang (x/y) en per-transcript status.
- Sidecar-endpoint `POST /client/hub/migrate` start een job (bestaande
  job-registry) die alle transcripten met `origin='local'` afloopt:
  1. push JSON + audio naar hub via endpoint A (HubClient, signed);
  2. poke de sync-puller en wacht tot de hub-kopie lokaal terug is
     (zelfde tid in de synced-dir, geïndexeerd met `origin='hub'`);
  3. verifieer: segmentaantal en speakers van de synced kopie gelijk aan
     het origineel;
  4. verplaats origineel (json + txt + audio) naar de bestaande trash
     (`speechtotext/api/trash.py`) en de-indexeer.
- Resumable/idempotent: transcripten die de hub al heeft (stap 1 antwoordt
  `exists`) gaan direct door naar stap 2-4; een afgebroken run kan gewoon
  opnieuw gestart worden.
- Faalt één transcript, dan blijft het origineel onaangeroerd en gaat de
  job door met de rest; het rapport (JobRecord.result) somt mislukte id's op.

### D. RAG-proxy (laptop)

- In `routes_transcripts.list_transcripts`: is de sidecar gejoined en
  `semantic=1`, forward dan de query (signed, via HubClient) naar de hub
  en retourneer diens antwoord ongewijzigd (zelfde hit-formaat; tid's zijn
  identiek aan de gesyncte kopieën, dus jump-to-segment werkt).
- `POST /library/ask` idem: forward naar hub. De hub-`job_id` leeft op de
  hub, dus de laptop-sidecar maakt een eigen JobRecord aan dat de hub-job
  volgt (hub-job-id in het record; `GET /jobs/{id}` haalt status+result bij
  de hub op voor zulke proxy-jobs), zodat de bestaande AskPanel-polling
  ongewijzigd blijft werken.
- Hub onbereikbaar → 503 met duidelijke melding (bestaande
  `searchError`/AskPanel-foutpaden tonen die al).
- Niet gejoined → huidig gedrag (lokale embedder of 503 als die er niet is).

### C. Offline-capture-toggle

- Config: `hub.offline_capture: "local" | "queue"`, default `"local"`;
  exposed via de bestaande config-routes + Settings-UI (radio/select naast
  de join-kaart).
- Joined + hub onbereikbaar bij een capture:
  - `queue`: huidig gedrag (audio-outbox, hub transcribeert later).
  - `local`: lokale pipeline draait direct; bij voltooiing gaat het
    afgeronde transcript een transcript-outbox in
    (`<app-data>/hub/outbox-transcripts/`, zelfde mechanica als de
    audio-outbox) die de hub-runtime-sweep via endpoint A pusht zodra er
    weer verbinding is; na geslaagde push + terugsync wordt het lokale
    origineel gearchiveerd zoals bij B.
- Online capture: ongewijzigd (hub transcribeert).

## Foutafhandeling

- Migratie: netwerkfout mid-run → job faalt op dat transcript, origineel
  blijft; rerun pakt de rest. Geen enkele verwijdering vóór geverifieerde
  terugsync.
- Proxy: timeouts kort houden (zoekverzoek ~5s) zodat de zoekbalk niet
  hangt; fout → 503 → bestaande foutweergave.
- Import: corrupte JSON → 422; te groot → 413; onbekende velden blijven
  behouden (doc wordt as-is opgeslagen, niet geherserialiseerd door een
  pydantic-model).

## Testen

- A: import happy path (audio_path herschreven, geïndexeerd, chunks
  geschreven), idempotentie (tweede import → exists), signed-auth
  geweigerd zonder geldige handtekening, JSON-only import.
- B: migratiejob met gemockte HubClient + loopback (bestaand
  `sync_test_transport()`-patroon): push → terugsync → verificatie →
  trash; faal-één-ga-door; resume na afbreken; nooit trash zonder
  geverifieerde synced kopie.
- D: joined → semantic forward (gemockte HubClient) retourneert hub-hits;
  niet joined → lokaal pad; hub down → 503. Ask-forward + job-proxy.
- C: toggle in config-roundtrip; offline+local → lokale pipeline +
  transcript-outbox-entry; sweep pusht en archiveert; offline+queue →
  huidig gedrag.

## Bewust weggelaten (YAGNI)

Dedup-weergave voor niet-gemigreerde duplicaten, audio-loze migratie-optie
in de UI, embedding-delegatie, automatische (knop-loze) migratie,
bidirectionele conflictresolutie buiten de bestaande CRDT-ops.
