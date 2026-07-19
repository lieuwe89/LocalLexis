# UX-polish na eerste devicetest — design

**Datum:** 2026-07-19
**Status:** goedgekeurd door gebruiker
**Context:** eerste echte gebruik van v0.18.2 (RAG + hub-SSOT) leverde vier
UX-punten op. Alle vier zijn additief; geen schemawijzigingen.

## 1. Voetnoot-bronkoppeling in Ask-antwoorden

De LLM citeert `[n]`; de nummering in `build_ask_messages` volgt exact de
volgorde van de `sources`-lijst op het JobRecord (zelfde chunks-array in
`run_ask_job`). Fix is puur UI: AskPanel-bronknoppen tonen `[n] m:ss`
(nummer + tijdstempel), zodat `[2]` in het antwoord visueel bij de tweede
knop hoort. Zelfde in de hub-web-UI (zelfde component). Geen API-wijziging.

## 2. Audio overal afspeelbaar — streamen via de hub

- Hub-kant: `GET /transcripts/{tid}/audio` accepteert device-signed
  requests (route in `_is_lan_signed_route`, handler krijgt
  `verify_admin_or_device_or_anonymous`, zelfde patroon als de
  zoek/ask-routes uit Task 7 van het hub-SSOT-plan).
- Laptop-kant: in `get_transcript_audio`, als het audiobestand lokaal
  ontbreekt én de sidecar joined is → proxy het verzoek gesigneerd naar de
  hub. **Range-header passthrough** beide kanten op (de hub-route doet al
  206/Content-Range), respons gestreamd doorgegeven (geen buffering van
  hele bestanden), status/headers doorgekopieerd. Recursion guard zoals de
  andere forwards (ContextVar): self-joined → val terug op lokaal 404.
- Hub onbereikbaar → 503 met duidelijke melding; de bestaande AudioPanel
  degradeert al netjes.
- Verwachte flow na migratie: gemigreerde transcripten hebben hub-paden in
  hun doc → lokaal bestand ontbreekt → stream van hub. Lokale (offline)
  opnames blijven lokaal spelen.

## 3. Semantische hits: beste zin oplichten

- Hub-kant, in `LibraryDB.semantic_search` (of een helper ernaast): voor
  de hits die daadwerkelijk geretourneerd worden (max `_HITS_PER_TRANSCRIPT`
  per transcript × aantal transcripten) wordt de chunktekst in zinnen
  gesplitst (simpele regex op `.!?`-grenzen; geen NLP-dependency), de
  zinnen ge-embed (model is warm; batch per zoekopdracht) en de zin met de
  hoogste cosine t.o.v. de query gemarkeerd: `snippet_parts` wordt
  `[{text: vóór, match: False}, {text: beste zin, match: True},
  {text: ná, match: False}]`.
- De bestaande hit-UI rendert `match: True` al als `<mark>` — geen
  UI-wijziging nodig.
- Begrenzing: alleen voor de geretourneerde hits (niet alle kandidaten);
  bij embedfout → ongemarkeerde snippet zoals nu (graceful).
- Chunks van ~150-300 woorden ≈ 8-15 zinnen per hit; tientallen hits ⇒
  honderden zin-embeddings per query — MiniLM op CPU doet dat in
  subseconde-batches. Ponytail-comment met dit plafond erbij.

## 4. Ask-voortgang zichtbaar

- AskPanel toont tijdens het pollen de job-stage: `retrieve` →
  "Searching your library…", `ask`/`ask@hub` → "Writing answer…",
  met een bescheiden CSS-spinner/pulserende dots naast de tekst.
  Fallback-tekst "Working…" voor onbekende stages.
- Geen API-wijziging: stage zit al in het gepollde JobRecord (ook voor
  proxied jobs — get_job kopieert de hub-stage al over).

## Testen

1. Bronknop-labels: `[1]`/`[2]` + tijden gerenderd in volgorde.
2. Audio-proxy: hub-kant device-signed audio (200 + 206 met Range);
   laptop-kant: lokaal-bestand-weg + joined → proxy met Range-passthrough
   (gemockte HubClient/transport), hub down → 503, self-joined → geen
   recursie, lokaal bestand aanwezig → geen proxy.
3. Beste-zin: bekende fake-embeddings → juiste zin gemarkeerd; embedfout →
   snippet zonder markering; zinsplitsing op randgevallen (één zin, lege
   tekst).
4. Ask-stages: gemockte poll-responses met stage retrieve→ask→complete →
   juiste teksten verschijnen en verdwijnen.

## Bewust weggelaten (YAGNI)

Letterlijke-term-highlight bovenop de beste zin, audio-caching op de
laptop, citation-parsing in het antwoord (nummering blijft cosmetisch
gekoppeld), voortgangspercentages in het Ask-paneel.
