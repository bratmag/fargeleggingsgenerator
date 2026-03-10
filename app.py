import base64
import hashlib
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flask import Flask, request, send_file, render_template_string
from openai import OpenAI, BadRequestError
from PIL import Image, ImageOps
from werkzeug.exceptions import RequestEntityTooLarge

# PDF (ReportLab)
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

client = OpenAI()

# -----------------------------
# Limits / config
# -----------------------------
MAX_FILES_SINGLE = 1
BOOKLET_MIN = 2
BOOKLET_MAX = 4
MAX_PARALLEL_WORKERS = 4  # keep <= BOOKLET_MAX

# Total request size limit (Render safety)
MAX_CONTENT_LENGTH_MB = 25

# OpenAI output size
SIDE_WIDTH = 1024
SIDE_HEIGHT = 1536
IMAGE_SIZE_STR = f"{SIDE_WIDTH}x{SIDE_HEIGHT}"

# Input preprocessing sizes
OPENAI_INPUT_MAX_DIM = 1600
PDF_IMAGE_MAX_DIM = 2200
SINGLE_COMBO_MAX_DIM = 2200

# Cache
CACHE_DIR = Path("/tmp/coloring_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Prompt
# -----------------------------
BASE_PROMPT = """
Convert this photo into a clean, black-and-white line drawing coloring page
for young children (around 4–7 years old).

Requirements:
- Keep the main people and important objects from the photo.
- Simplify faces into friendly cartoon-like features.
- Use clear, bold outlines and avoid shading and tiny details.
- Background should be simplified but recognizable (only a few important lines).
- White background, no grey shading, only black lines.
"""

HTML_PAGE = """
<!doctype html>
<html lang="no">
  <head>
    <meta charset="utf-8">
    <title>Fargeleggingsgenerator</title>
    <style>
      :root { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #0f172a; }
      * { box-sizing: border-box; }
      body {
        margin: 0; padding: 2rem 1rem; display: flex; align-items: center; justify-content: center; min-height: 100vh;
        background-image: url('/static/background-kids.png');
        background-size: cover; background-position: center; background-repeat: no-repeat; background-attachment: fixed;
      }
      .card {
        background: rgba(255, 255, 255, 0.88);
        backdrop-filter: blur(10px);
        padding: 2rem 2.5rem;
        border-radius: 1.25rem;
        box-shadow: 0 18px 40px rgba(15,23,42,0.25);
        max-width: 720px; width: 100%;
      }
      h1 { margin: 0 0 0.35rem 0; font-size: 1.8rem; }
      .sub { margin: 0 0 1.2rem 0; color: #6b7280; font-size: 0.95rem; line-height: 1.5; }

      .dropzone {
        position: relative;
        margin: 0 0 0.6rem 0;
        border: 2px dashed #cbd5f5;
        border-radius: 0.9rem;
        padding: 1.5rem 1.25rem;
        text-align: center;
        background: #f9fafb;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
      }
      .dropzone.dragover { background: #eef2ff; border-color: #4f46e5; box-shadow: 0 0 0 2px rgba(79,70,229,0.3); }
      .dropzone input[type="file"] { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
      .dropzone-title { font-weight: 600; margin-bottom: 0.3rem; pointer-events: none; }
      .dropzone-sub { font-size: 0.9rem; color: #6b7280; pointer-events: none; }

      .file-list { margin: 0 0 1.0rem 0; font-size: 0.8rem; color: #4b5563; text-align: left; }
      .file-list-empty { color: #9ca3af; }

      .controls-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; }
      .control-group { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.9rem; color: #374151; }
      select { padding: 0.35rem 0.7rem; border-radius: 999px; border: 1px solid #d1d5db; font-size: 0.9rem; background: #f9fafb; }
      button {
        background: #4f46e5; color: white; border: none; border-radius: 999px;
        padding: 0.65rem 1.5rem; font-size: 0.95rem; cursor: pointer; white-space: nowrap;
      }
      button:hover { background: #4338ca; }
      .hint { margin-top: 0.9rem; font-size: 0.8rem; color: #6b7280; }
      .footer { margin-top: 1.2rem; font-size: 0.75rem; color: #9ca3af; }

      .overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: flex; align-items: center; justify-content: center; z-index: 50; }
      .overlay.hidden { display: none; }
      .overlay-box {
        background: #ffffff; padding: 1.5rem 1.75rem; border-radius: 0.9rem;
        box-shadow: 0 18px 40px rgba(15,23,42,0.3);
        max-width: 380px; text-align: center; font-size: 0.95rem;
      }
      .loader {
        width: 36px; height: 36px; border-radius: 999px; border: 3px solid #e5e7eb; border-top-color: #4f46e5;
        animation: spin 0.9s linear infinite; margin: 0 auto 0.9rem auto;
      }
      @keyframes spin { to { transform: rotate(360deg); } }

      @media (max-width: 600px) {
        .card { padding: 1.5rem 1.25rem; }
        .controls-row { flex-direction: column; align-items: stretch; }
        button { width: 100%; text-align: center; justify-content: center; }
        .file-list { text-align: center; }
      }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Fargeleggingsgenerator</h1>
      <p class="sub">
        Last opp bilder og få et kombobilde (original + fargeleggingsark). Du kan også lage en PDF (2–4 bilder) for utskrift.
      </p>

      <form id="form" action="/process" method="post" enctype="multipart/form-data">
        <fieldset style="border:none; padding:0; margin: 0 0 1rem 0;">
          <div style="display:flex; gap:1rem; flex-wrap:wrap;">
            <label class="control-group">
              <input type="radio" name="mode" value="single" checked>
              Enkeltbilde
            </label>
            <label class="control-group">
              <input type="radio" name="mode" value="booklet">
              Fargeleggingshefte (PDF)
            </label>
          </div>
        </fieldset>

        <div id="singleBox">
          <label class="dropzone" id="dropzoneSingle">
            <input id="file-input-single" type="file" name="images" accept="image/*">
            <div class="dropzone-title">Slipp ett bilde her</div>
            <div class="dropzone-sub">eller klikk for å velge ett bilde</div>
          </label>
          <div id="file-list-single" class="file-list file-list-empty">Ingen filer valgt ennå.</div>
        </div>

        <div id="bookletBox" style="display:none;">
          <label class="dropzone" id="dropzoneBooklet">
            <input id="file-input-booklet" type="file" name="booklet_images" accept="image/*" multiple>
            <div class="dropzone-title">Slipp 2–4 bilder her</div>
            <div class="dropzone-sub">eller klikk for å velge flere bilder</div>
          </label>
          <div id="file-list-booklet" class="file-list file-list-empty">Ingen filer valgt ennå.</div>

          <div class="controls-row" style="margin-bottom: 0.5rem;">
            <div class="control-group">
              <label for="paper">Format:</label>
              <select name="paper" id="paper">
                <option value="A4" selected>A4</option>
                <option value="A5">A5</option>
              </select>
            </div>
          </div>

          <div class="controls-row" style="margin-bottom: 0.5rem;">
            <div class="control-group">
              <label>Layout:</label>
              <label class="control-group">
                <input type="radio" name="layout" value="combo"> Komboside
              </label>
              <label class="control-group">
                <input type="radio" name="layout" value="album" checked> Album (1 bilde per side)
              </label>
            </div>
          </div>
        </div>

        <div class="controls-row">
          <div class="control-group">
            <label for="detail">Detaljnivå:</label>
            <select name="detail" id="detail">
              <option value="simple">Ren og enkel (minst detaljer)</option>
              <option value="normal" selected>Normal</option>
              <option value="detailed">Mer detaljer</option>
            </select>
          </div>
          <button type="submit" id="submitBtn">Generer fargeleggingsark</button>
        </div>

        <p class="hint" id="hintText">
          Last opp ett bilde for kombobilde.
        </p>
      </form>

      <div class="footer">
        Bildene sendes til OpenAI for å generere tegningen, men lagres ikke permanent på serveren.
      </div>
    </div>

    <div id="overlay" class="overlay hidden">
      <div class="overlay-box">
        <div class="loader"></div>
        <div id="overlayText">Genererer …</div>
        <div style="font-size:0.8rem; color:#6b7280; margin-top:0.4rem;">Dette kan ta litt tid.</div>
      </div>
    </div>

    <script>
      const form = document.getElementById('form');
      const overlay = document.getElementById('overlay');
      const overlayText = document.getElementById('overlayText');

      const singleBox = document.getElementById('singleBox');
      const bookletBox = document.getElementById('bookletBox');
      const hintText = document.getElementById('hintText');
      const submitBtn = document.getElementById('submitBtn');

      const singleInput = document.getElementById('file-input-single');
      const bookletInput = document.getElementById('file-input-booklet');

      const singleList = document.getElementById('file-list-single');
      const bookletList = document.getElementById('file-list-booklet');

      const paperSelect = document.getElementById('paper');
      const layoutRadios = document.querySelectorAll('input[name="layout"]');

      function setMode(mode) {
        const isSingle = mode === 'single';

        singleBox.style.display = isSingle ? 'block' : 'none';
        bookletBox.style.display = isSingle ? 'none' : 'block';

        // Ikke bruk required på filfeltene.
        // Kun disable inaktiv modus.
        singleInput.disabled = !isSingle;
        bookletInput.disabled = isSingle;
        paperSelect.disabled = isSingle;
        layoutRadios.forEach(r => r.disabled = isSingle);

        submitBtn.textContent = isSingle ? 'Generer fargeleggingsark' : 'Generer PDF';
        overlayText.textContent = isSingle ? 'Genererer fargeleggingsark …' : 'Genererer PDF …';

        hintText.textContent = isSingle
          ? 'Last opp ett bilde for kombobilde.'
          : 'PDF: last opp 2–4 bilder. Album gir 1 bilde per side.';
      }

      document.querySelectorAll('input[name="mode"]').forEach(r => {
        r.addEventListener('change', () => {
          const mode = document.querySelector('input[name="mode"]:checked').value;
          setMode(mode);
        });
      });

      function updateSingleList() {
        const files = singleInput.files;
        if (!files || files.length === 0) {
          singleList.textContent = 'Ingen filer valgt ennå.';
          singleList.classList.add('file-list-empty');
          return;
        }
        singleList.classList.remove('file-list-empty');
        singleList.textContent = `Valgt fil: ${files[0].name}`;
      }

      function updateBookletList() {
        const files = bookletInput.files;
        if (!files || files.length === 0) {
          bookletList.textContent = 'Ingen filer valgt ennå.';
          bookletList.classList.add('file-list-empty');
          return;
        }
        bookletList.classList.remove('file-list-empty');
        bookletList.textContent = `Valgt ${files.length} filer`;
      }

      singleInput.addEventListener('change', updateSingleList);
      bookletInput.addEventListener('change', updateBookletList);

      function attachDnD(dropzoneEl, inputEl, updateFn, singleOnly=false) {
        dropzoneEl.addEventListener('dragover', (e) => {
          e.preventDefault();
          dropzoneEl.classList.add('dragover');
        });

        dropzoneEl.addEventListener('dragleave', () => {
          dropzoneEl.classList.remove('dragover');
        });

        dropzoneEl.addEventListener('drop', (e) => {
          e.preventDefault();
          dropzoneEl.classList.remove('dragover');

          const files = e.dataTransfer.files;
          if (!files || files.length === 0) return;

          const dt = new DataTransfer();
          if (singleOnly) {
            dt.items.add(files[0]);
          } else {
            for (const f of files) dt.items.add(f);
          }
          inputEl.files = dt.files;
          updateFn();
        });
      }

      attachDnD(document.getElementById('dropzoneSingle'), singleInput, updateSingleList, true);
      attachDnD(document.getElementById('dropzoneBooklet'), bookletInput, updateBookletList, false);

      let overlayTimeout = null;
      form.addEventListener('submit', () => {
        const mode = document.querySelector('input[name="mode"]:checked').value;
        console.log('Submitting mode:', mode);

        overlay.classList.remove('hidden');
        if (overlayTimeout) clearTimeout(overlayTimeout);
        overlayTimeout = setTimeout(() => overlay.classList.add('hidden'), 10 * 60 * 1000);
      });

      window.addEventListener('focus', () => {
        if (!overlay.classList.contains('hidden')) {
          setTimeout(() => overlay.classList.add('hidden'), 300);
        }
      });

      setMode('single');
    </script>
  </body>
</html>
"""


# -----------------------------
# Data structures
# -----------------------------
@dataclass
class PreparedImage:
    original_filename: str
    original_bytes: bytes
    openai_input_bytes: bytes
    pdf_bytes: bytes


# -----------------------------
# Helpers
# -----------------------------
def build_prompt(detail_level: str) -> str:
    extra = ""
    if detail_level == "simple":
        extra = "\nMake the drawing very simple with thick lines and large areas for coloring."
    elif detail_level == "detailed":
        extra = "\nKeep some extra details and textures, but still suitable for children to color."
    return BASE_PROMPT + extra


def sanitize_stem(filename: str) -> str:
    stem = (filename or "bilde").rsplit(".", 1)[0].strip()
    stem = stem.replace(" ", "-")
    stem = re.sub(r"[^A-Za-z0-9ÆØÅæøå.-]+", "-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return stem or "bilde"


def pil_image_from_bytes(image_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(image_bytes)) as raw:
        img = ImageOps.exif_transpose(raw)
        return img.convert("RGB")


def image_to_jpeg_bytes(img: Image.Image, quality: int = 88) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def prepare_image_variants(image_bytes: bytes, filename: str) -> PreparedImage:
    """
    Prepares two reusable variants:
    - openai_input_bytes: JPEG, auto-rotated, RGB, max 1600 px
    - pdf_bytes: JPEG, auto-rotated, RGB, max 2200 px
    """
    start = time.time()
    base_img = pil_image_from_bytes(image_bytes)

    openai_img = base_img.copy()
    if max(openai_img.size) > OPENAI_INPUT_MAX_DIM:
        openai_img.thumbnail((OPENAI_INPUT_MAX_DIM, OPENAI_INPUT_MAX_DIM), Image.LANCZOS)
    openai_input_bytes = image_to_jpeg_bytes(openai_img, quality=88)
    openai_img.close()

    pdf_img = base_img.copy()
    if max(pdf_img.size) > PDF_IMAGE_MAX_DIM:
        pdf_img.thumbnail((PDF_IMAGE_MAX_DIM, PDF_IMAGE_MAX_DIM), Image.LANCZOS)
    pdf_bytes = image_to_jpeg_bytes(pdf_img, quality=90)
    pdf_img.close()
    base_img.close()

    print(
        f"Preprocess '{filename}': orig={len(image_bytes)/1024:.0f}KB, "
        f"openai={len(openai_input_bytes)/1024:.0f}KB, pdf={len(pdf_bytes)/1024:.0f}KB "
        f"på {time.time() - start:.1f} sek",
        flush=True,
    )

    return PreparedImage(
        original_filename=filename,
        original_bytes=image_bytes,
        openai_input_bytes=openai_input_bytes,
        pdf_bytes=pdf_bytes,
    )


def cache_key(image_bytes: bytes, detail_level: str) -> str:
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(detail_level.encode("utf-8"))
    h.update(IMAGE_SIZE_STR.encode("utf-8"))
    h.update(b"prompt-v1")
    return h.hexdigest()


def get_cached_coloring(image_bytes: bytes, detail_level: str) -> bytes | None:
    key = cache_key(image_bytes, detail_level)
    path = CACHE_DIR / f"{key}.png"
    if path.exists():
        print(f"Cache hit: {path.name}", flush=True)
        return path.read_bytes()
    return None


def set_cached_coloring(image_bytes: bytes, detail_level: str, coloring_bytes: bytes) -> None:
    key = cache_key(image_bytes, detail_level)
    path = CACHE_DIR / f"{key}.png"
    path.write_bytes(coloring_bytes)


def generate_coloring_bytes(prepared: PreparedImage, detail_level: str) -> bytes:
    """Calls OpenAI image API and returns PNG bytes for the coloring image."""
    cached = get_cached_coloring(prepared.openai_input_bytes, detail_level)
    if cached is not None:
        return cached

    prompt = build_prompt(detail_level)

    buf = io.BytesIO(prepared.openai_input_bytes)
    buf.name = "upload.jpg"

    start = time.time()
    try:
        result = client.images.edit(
            model="gpt-image-1",
            image=buf,
            prompt=prompt,
            size=IMAGE_SIZE_STR,
            output_format="png",
            quality="high",
        )
    except BadRequestError as e:
        if "moderation_blocked" in str(e):
            raise ValueError("moderation_blocked")
        raise

    elapsed = time.time() - start
    print(
        f"OpenAI image generation tok {elapsed:.1f} sek "
        f"(input {len(prepared.openai_input_bytes)/1024:.0f}KB, fil '{prepared.original_filename}')",
        flush=True,
    )

    image_base64 = result.data[0].b64_json
    coloring_bytes = base64.b64decode(image_base64)
    set_cached_coloring(prepared.openai_input_bytes, detail_level, coloring_bytes)
    return coloring_bytes


def generate_coloring_batch_parallel(prepared_images: list[PreparedImage], detail: str) -> list[bytes]:
    """Generate coloring images in parallel and preserve original order."""
    batch_start = time.time()
    results: list[bytes | None] = [None] * len(prepared_images)

    max_workers = min(MAX_PARALLEL_WORKERS, len(prepared_images))
    print(
        f"Starter parallell OpenAI-generering: {len(prepared_images)} bilder, workers={max_workers}",
        flush=True,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(generate_coloring_bytes, prepared, detail): idx
            for idx, prepared in enumerate(prepared_images)
        }

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
                print(f"Parallelt bilde {idx + 1} ferdig", flush=True)
            except ValueError as e:
                if "moderation_blocked" in str(e):
                    raise ValueError(f"moderation_blocked_{idx + 1}")
                raise

    print(f"Parallell batch ferdig på {time.time() - batch_start:.1f} sek", flush=True)
    return [r for r in results if r is not None]


def combine_side_by_side_bytes(original_pdf_bytes: bytes, coloring_bytes: bytes) -> bytes:
    """
    Single mode PNG output:
    builds a combined PNG with original left + coloring right.
    Uses preprocessed original bytes for lower memory usage.
    """
    orig = pil_image_from_bytes(original_pdf_bytes)
    col = pil_image_from_bytes(coloring_bytes)

    canvas_img = Image.new("RGB", (SIDE_WIDTH * 2, SIDE_HEIGHT), color=(255, 255, 255))

    def place_in_box(img: Image.Image, box_left: int):
        img_copy = img.copy()
        if max(img_copy.size) > SINGLE_COMBO_MAX_DIM:
            img_copy.thumbnail((SINGLE_COMBO_MAX_DIM, SINGLE_COMBO_MAX_DIM), Image.LANCZOS)
        img_copy.thumbnail((SIDE_WIDTH, SIDE_HEIGHT), Image.LANCZOS)
        x_offset = box_left + (SIDE_WIDTH - img_copy.width) // 2
        y_offset = (SIDE_HEIGHT - img_copy.height) // 2
        canvas_img.paste(img_copy, (x_offset, y_offset))
        img_copy.close()

    place_in_box(orig, box_left=0)
    place_in_box(col, box_left=SIDE_WIDTH)

    out_buf = io.BytesIO()
    canvas_img.save(out_buf, format="PNG")
    out_buf.seek(0)

    orig.close()
    col.close()
    canvas_img.close()

    return out_buf.getvalue()


def pil_to_imagereader(img: Image.Image) -> ImageReader:
    """
    Fast path: use ImageReader directly on PIL image.
    Fallback: convert to JPEG bytes if environment is picky.
    """
    try:
        return ImageReader(img)
    except Exception:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90, optimize=True)
        buf.seek(0)
        return ImageReader(buf)


def _pdf_page_geometry(paper: str):
    if paper not in ("A4", "A5"):
        paper = "A4"
    pagesize = A4 if paper == "A4" else A5
    page_w, page_h = pagesize

    # Margins (binding-left friendly)
    inner = 20 * mm
    outer = 12 * mm
    top = 12 * mm
    bottom = 15 * mm

    x0 = inner
    y0 = bottom
    usable_w = page_w - inner - outer
    usable_h = page_h - top - bottom
    return pagesize, page_w, page_h, (x0, y0, usable_w, usable_h)


def _draw_fit(c, pil_img: Image.Image, x0: float, y0: float, usable_w: float, usable_h: float):
    iw, ih = pil_img.size
    scale = min(usable_w / iw, usable_h / ih)
    tw = iw * scale
    th = ih * scale
    dx = x0 + (usable_w - tw) / 2
    dy = y0 + (usable_h - th) / 2
    c.drawImage(pil_to_imagereader(pil_img), dx, dy, width=tw, height=th, mask="auto")


def _draw_fit_in_box(c, pil_img: Image.Image, box_x: float, box_y: float, box_w: float, box_h: float):
    iw, ih = pil_img.size
    scale = min(box_w / iw, box_h / ih)
    tw = iw * scale
    th = ih * scale
    dx = box_x + (box_w - tw) / 2
    dy = box_y + (box_h - th) / 2
    c.drawImage(pil_to_imagereader(pil_img), dx, dy, width=tw, height=th, mask="auto")


def build_pdf_combo_direct_from_pairs(
    original_pdf_bytes_list: list[bytes],
    coloring_bytes_list: list[bytes],
    paper: str,
) -> bytes:
    """
    Combo mode, optimized:
    Draw original directly into left half and coloring directly into right half.
    No intermediate combined PNG.
    """
    pagesize, _page_w, _page_h, (x0, y0, usable_w, usable_h) = _pdf_page_geometry(paper)

    gutter = 6 * mm
    half_w = (usable_w - gutter) / 2
    left_x = x0
    right_x = x0 + half_w + gutter

    out = io.BytesIO()
    c = pdfcanvas.Canvas(out, pagesize=pagesize)
    c.setTitle("Fargeleggingshefte (Kombosider)")
    c.setAuthor("Fargeleggingsgenerator")

    for idx, (original_pdf_bytes, coloring_bytes) in enumerate(zip(original_pdf_bytes_list, coloring_bytes_list), start=1):
        page_start = time.time()

        orig = pil_image_from_bytes(original_pdf_bytes)
        col = pil_image_from_bytes(coloring_bytes)

        _draw_fit_in_box(c, orig, left_x, y0, half_w, usable_h)
        _draw_fit_in_box(c, col, right_x, y0, half_w, usable_h)
        c.showPage()

        orig.close()
        col.close()

        print(f"Komboside {idx} direkte i PDF på {time.time() - page_start:.1f} sek", flush=True)

    c.save()
    out.seek(0)
    return out.getvalue()


def build_pdf_album_from_pairs(
    original_pdf_bytes_list: list[bytes],
    coloring_bytes_list: list[bytes],
    paper: str,
) -> bytes:
    """Album mode: page 1 original, page 2 coloring."""
    pagesize, _page_w, _page_h, (x0, y0, usable_w, usable_h) = _pdf_page_geometry(paper)

    out = io.BytesIO()
    c = pdfcanvas.Canvas(out, pagesize=pagesize)
    c.setTitle("Fargeleggingshefte (Album)")
    c.setAuthor("Fargeleggingsgenerator")

    for idx, (original_pdf_bytes, coloring_bytes) in enumerate(zip(original_pdf_bytes_list, coloring_bytes_list), start=1):
        pair_start = time.time()

        orig = pil_image_from_bytes(original_pdf_bytes)
        _draw_fit(c, orig, x0, y0, usable_w, usable_h)
        c.showPage()
        orig.close()

        col = pil_image_from_bytes(coloring_bytes)
        _draw_fit(c, col, x0, y0, usable_w, usable_h)
        c.showPage()
        col.close()

        print(f"Bildepar {idx} ferdig på {time.time() - pair_start:.1f} sek", flush=True)

    c.save()
    out.seek(0)
    return out.getvalue()


def handle_single_mode(detail: str, single_files):
    if not single_files or single_files[0].filename == "":
        raise ValueError("Ingen filer lastet opp.")

    if len(single_files) > MAX_FILES_SINGLE:
        raise ValueError(
            f"På grunn av begrensninger i serveren kan du foreløpig bare laste opp {MAX_FILES_SINGLE} bilde om gangen."
        )

    file = single_files[0]
    original_bytes = file.read()
    if not original_bytes:
        raise ValueError("Ingen gyldige bilder.")

    filename = file.filename or "bilde"
    prepared = prepare_image_variants(original_bytes, filename)

    try:
        coloring_bytes = generate_coloring_bytes(prepared, detail)
    except ValueError as e:
        if "moderation_blocked" in str(e):
            return (
                "Bildet ditt ble stoppet av sikkerhetssystemet til OpenAI. "
                "Prøv et annet bilde (mer klær, nøytral setting, ingen sensitive situasjoner).",
                400,
            )
        raise

    combined_png = combine_side_by_side_bytes(prepared.pdf_bytes, coloring_bytes)
    stem = sanitize_stem(filename)
    name = f"{stem}-combo.png"

    return send_file(
        io.BytesIO(combined_png),
        mimetype="image/png",
        as_attachment=True,
        download_name=name,
    )


def handle_booklet_mode(detail: str, booklet_files):
    paper = request.form.get("paper", "A4")
    layout = request.form.get("layout", "album")

    if len(booklet_files) < BOOKLET_MIN or len(booklet_files) > BOOKLET_MAX:
        raise ValueError(f"Last opp {BOOKLET_MIN}–{BOOKLET_MAX} bilder (du lastet opp {len(booklet_files)}).")

    originals_with_names: list[tuple[str, bytes]] = []
    for file in booklet_files:
        original_bytes = file.read()
        if original_bytes:
            originals_with_names.append((file.filename or "bilde", original_bytes))

    if len(originals_with_names) < BOOKLET_MIN:
        raise ValueError("Ingen gyldige bilder.")

    print("PDF request:", {"paper": paper, "layout": layout, "count": len(originals_with_names)}, flush=True)

    prepared_images = [prepare_image_variants(image_bytes, filename) for filename, image_bytes in originals_with_names]

    try:
        coloring_bytes_list = generate_coloring_batch_parallel(prepared_images, detail)
    except ValueError as e:
        if "moderation_blocked_" in str(e):
            return "Et av bildene ble stoppet av sikkerhetssystemet til OpenAI. Fjern det bildet og prøv igjen.", 400
        raise

    original_pdf_bytes_list = [prepared.pdf_bytes for prepared in prepared_images]

    pdf_start = time.time()
    if layout == "combo":
        pdf_bytes = build_pdf_combo_direct_from_pairs(original_pdf_bytes_list, coloring_bytes_list, paper=paper)
        title = "combo"
    else:
        pdf_bytes = build_pdf_album_from_pairs(original_pdf_bytes_list, coloring_bytes_list, paper=paper)
        title = "album"

    print(f"PDF generert på {time.time() - pdf_start:.1f} sek", flush=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"fargeleggingshefte-{title}-{paper}-{stamp}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# -----------------------------
# Flask app
# -----------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_e):
    return (
        f"Opplastingen er for stor. Prøv færre eller mindre bilder. Maks total størrelse er {MAX_CONTENT_LENGTH_MB} MB.",
        413,
    )


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE)


@app.route("/process", methods=["POST"])
def process():
    request_start = time.time()

    form_mode = request.form.get("mode", "single")
    detail = request.form.get("detail", "normal")

    single_files = [f for f in request.files.getlist("images") if f and f.filename]
    booklet_files = [f for f in request.files.getlist("booklet_images") if f and f.filename]

    # Robust modedeteksjon basert på hva som faktisk ble sendt inn
    if single_files and not booklet_files:
        mode = "single"
    elif booklet_files and not single_files:
        mode = "booklet"
    else:
        mode = form_mode

    print(
        f"Mode fra skjema: {form_mode} | tolket mode: {mode} | "
        f"single_files={len(single_files)} | booklet_files={len(booklet_files)}",
        flush=True,
    )

    try:
        if mode == "single":
            response = handle_single_mode(detail, single_files)
        elif mode == "booklet":
            response = handle_booklet_mode(detail, booklet_files)
        else:
            return "Ugyldig valg.", 400

        print(f"Hele request tok {time.time() - request_start:.1f} sek", flush=True)
        return response

    except ValueError as e:
        return str(e), 400


if __name__ == "__main__":
    app.run(debug=True)
