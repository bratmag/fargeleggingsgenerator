# Fargeleggingsgenerator

Web-app som gjør fotografier om til fargeleggingsark for barn.

Produksjon: https://fargeleggingsgenerator.onrender.com

## Funksjoner

- Last opp ett bilde og få et kombobilde med original og fargeleggingsark.
- Enkeltbilder og PDF-hefter vises som forhåndsvisning før brukeren velger å laste ned.
- Last opp 2-10 bilder og få et PDF-hefte.
- Velg A4/A5, albumlayout eller kombosider.
- Velg testmotor i UI-et: Mini/medium, Mini/høy, Standard/medium eller Standard/høy.
- Bildene normaliseres med Pillow før de sendes til OpenAI.
- PDF-er bygges direkte med ReportLab for lavere minnebruk.

## Teknologi

- Python
- Flask
- Pillow
- ReportLab
- OpenAI Images API
- Render
- Gunicorn

## OpenAI-oppsett

Appen bruker `client.images.edit` og standardmodellen er `gpt-image-1-mini` for lavere kostnad og raskere respons enn `gpt-image-1`.

Viktige miljøvariabler:

```bash
OPENAI_API_KEY=...
OPENAI_IMAGE_MODEL=gpt-image-1-mini
OPENAI_IMAGE_QUALITY=medium
OPENAI_INPUT_MAX_DIM=1280
PDF_IMAGE_MAX_DIM=1800
MAX_PARALLEL_WORKERS=2
BOOKLET_MAX=10
MAX_CONTENT_LENGTH_MB=50
MAX_REQUESTS_PER_WINDOW=8
RATE_LIMIT_WINDOW_SECONDS=3600
```

Miljøvariablene er fallback-defaults. I test-UI-et kan motor velges per generering, slik at samme bilde kan sammenlignes på tvers av modell og kvalitet.

## Lokal utvikling

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Serveren kjører på http://127.0.0.1:5000.

## Render

Anbefalt startkommando:

```bash
gunicorn app:app --timeout 600 --workers 1
```

Sett `OPENAI_API_KEY` som environment variable i Render. For små instanser bør `MAX_PARALLEL_WORKERS` holdes lav, gjerne `2`.

## Produksjonsnotater

- Det finnes en enkel in-memory rate limit per serverprosess.
- For offentlig trafikk bør dette byttes til en delt limiter, for eksempel Redis eller en betalings-/kvoteløsning.
- Cache ligger i `/tmp/coloring_cache` og er derfor midlertidig på Render.
- Forhåndsvisninger ligger midlertidig i `/tmp/coloring_previews` og ryddes etter omtrent en time.
- Maks opplastingsstørrelse, pikselgrense og bildefiltyper valideres før OpenAI-kall.
