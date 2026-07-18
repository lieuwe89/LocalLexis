# RAG voor de zoekfunctie — design

**Datum:** 2026-07-18
**Status:** goedgekeurd door gebruiker
**Scope:** semantisch zoeken (aparte toggle) + bibliotheek-brede Q&A met bronverwijzingen

## Doel

Twee features bovenop de bestaande FTS5-zoekindex:

1. **Semantisch zoeken** — zoeken op betekenis i.p.v. exacte woorden, als extra
   toggle naast de bestaande fuzzy/sort-toggles. Resultaten blijven gewone
   transcript-hits met jump-to-segment. Geen LLM nodig.
2. **Q&A (RAG)** — bibliotheek-breed "Vraag je bibliotheek"-paneel: vraag in
   natuurlijke taal → LLM-antwoord met klikbare bronverwijzingen naar
   transcript-segmenten. Gebruikt de bestaande summarize-LLM-provider.

Product-invariant blijft: alles on-device. Embeddings draaien in-process;
de LLM-call gaat naar de al geconfigureerde lokale OpenAI-compat provider
(Ollama/LM Studio).

## Architectuurkeuzes

| Beslissing | Keuze | Verworpen alternatieven |
|---|---|---|
| Vector-opslag/zoek | Numpy brute-force over de bestaande `embeddings`-BLOB-tabel, in-memory matrix-cache | sqlite-vec (extra binaire dep per platform), dedicated vector-DB (overkill voor persoonlijke bibliotheek) |
| Embedding-runtime | In-process sentence-transformers, lazy geladen zoals Whisper | Provider `/embeddings`-endpoint (dan werkt semantisch zoeken alleen mét draaiende provider) |
| Embedding-model | `paraphrase-multilingual-MiniLM-L12-v2` (NL+EN, 384 dims) | — |
| Semantisch in UI | Aparte toggle naast fuzzy/sort | Hybride auto-blend, alleen-fallback |
| Q&A-plek | Bibliotheek-breed paneel | Per-transcript veld |

Schaal-aanname: persoonlijke bibliotheek, orde 50k chunks. Brute-force
dot-product is dan enkele ms. Upgrade-pad naar sqlite-vec als de bibliotheek
ooit >500k chunks wordt.

## Indexering

- **Chunks:** segment-vensters van ~150–300 tokens; aangrenzende segmenten
  samengevoegd. Opslag in de bestaande `chunks`-tabel (`transcript_id`, `idx`,
  `start_time`, `end_time`, `text`, `token_count`). Tijden zorgen dat een
  bronverwijzing altijd naar een segment kan springen.
- **Embeddings:** in de bestaande `embeddings`-tabel (`chunk_id`, `model`,
  `dim`, `vector` BLOB, float32 little-endian). De `model`-kolom fungeert als
  versie: wijkt die af van het geconfigureerde model, dan her-indexeren.
- **Wanneer:** piggyback op het bestaande `upsert_path`-pad (nieuw/gewijzigd
  transcript → chunks + embeddings bijwerken) plus een achtergrond-backfilljob
  die de bestaande bibliotheek indexeert. Verwijderen loopt mee via de
  bestaande `ON DELETE CASCADE`.
- **Modelload:** lazy, pas bij eerste embed-aanroep; sidecar-start wordt niet
  trager. Modeldownload (~470MB incl. deps) eenmalig, zoals Whisper-modellen.

## Semantisch zoeken

- Bestaand endpoint krijgt queryparam `semantic=true` naast `fuzzy`/`sort`.
- Flow: query embedden → dot-product tegen in-memory matrix (cache
  geïnvalideerd bij index-mutatie) → top-N chunks → mappen naar hetzelfde
  hit-formaat als FTS5-resultaten (transcript + segment + snippet + jump).
- UI: derde toggle naast fuzzy/sort; bestaande hit-lijst en jump-to-segment
  worden hergebruikt, geen nieuwe resultaat-UI.
- Werkt zonder LLM-provider.

## Q&A (RAG)

- **Endpoint:** `POST /library/ask` met `{question}` → job (bestaande
  job-registry, zoals summarize), dus geen hangende HTTP-requests.
- **Flow:** vraag embedden → top-k chunks (k ≈ 8) → prompt met chunks +
  bronlabels naar bestaande `OpenAICompatProvider.chat()` (zelfde config als
  summarize) → antwoord + bronnenlijst `[{transcript_id, start_time,
  end_time}]`.
- **UI:** "Vraag je bibliotheek"-paneel in de library-view: vraagveld,
  antwoord, bronnen klikbaar naar segment (hergebruik jump-mechanisme).
- **Geen provider geconfigureerd:** paneel meldt dat netjes; semantisch
  zoeken blijft gewoon werken.

## Foutafhandeling

- Embedding-model niet te downloaden / niet geladen: semantische toggle en
  Q&A geven een duidelijke foutmelding; FTS5-zoek blijft onaangetast.
- Provider-fouten in Q&A: via de bestaande `ProviderError`-afhandeling van
  summarize-jobs.
- Backfill is idempotent en hervat na herstart (chunks/embeddings die al
  bestaan met het juiste model worden overgeslagen).

## Testen

- Unit: chunker (segmentgrenzen, tijden, tokenlimieten), vectorzoek
  (bekende embeddings → verwachte ranking), cache-invalidatie na upsert.
- API: `semantic=true` respons-formaat gelijk aan FTS5-formaat; `/library/ask`
  jobflow met gemockte provider; gedrag zonder provider.
- Embedding-model wordt in tests gemockt (geen 470MB-download in CI).

## Bewust weggelaten (YAGNI)

Reranker/cross-encoder, chat-historie/conversatiegeheugen, streaming
antwoorden, hybride auto-blend ranking. Toevoegen als de basis tekortschiet.
