import base64
import io
from datetime import datetime

from flask import Flask, request, send_file, render_template_string
from openai import OpenAI, BadRequestError
from PIL import Image, ImageOps

# PDF (ReportLab)
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

client = OpenAI()

# Maks antall bilder for enkeltbilde-modus (holdes 1)
MAX_FILES_SINGLE = 1

# Maks antall bilder for hefte/PDF (MVP)
BOOKLET_MIN = 2
BOOKLET_MAX = 4

# Standard størrelse på hver "side" som OpenAI genererer (fargeleggingsbildet)
SIDE_WIDTH = 1024
SIDE_HEIGHT = 1536
IMAGE_SIZE_STR = f"{SIDE_WIDTH}x{SIDE_HEIGHT}"

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
          Foreløpig støttes ett bilde om gangen. Større opplastinger kan gjøre at serveren stopper.
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

      function setMode(mode) {
        const isSingle = mode === 'single';
        singleBox.style.display = isSingle ? 'block' : 'none';
        bookletBox.style.display = isSingle ? 'none' : 'block';

        submitBtn.textContent = isSingle ? 'Generer fargeleggingsark' : 'Generer PDF';
        overlayText.textContent = isSingle ? 'Genererer fargeleggingsark …' : 'Genererer PDF …';

        hintText.textContent = isSingle
          ? 'Foreløpig støttes ett bilde om gangen. Større opplastinger kan gjøre at serveren stopper.'
          : 'PDF: maks 4 bilder. Album gir 1 bilde per side.';
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
        dropzoneEl.addEventListener('dragover', (e) => { e.preventDefault(); dropzoneEl.classList.add('dragover'); });
        dropzoneEl.addEventListener('dragleave', () => { dropzoneEl.classList.remove('dragover'); });
        dropzoneEl.addEventListener('drop', (e) => {
          e.preventDefault();
          dropzoneEl.classList.remove('dragover');
          const files = e.dataTransfer.files;
          if (!files || files.length === 0) return;
          const dt = new DataTransfer();
          if (singleOnly) dt.items.add(files[0]);
          else for (const f of files) dt.items.add(f);
          inputEl.files = dt.files;
          updateFn();
        });
      }

      attachDnD(document.getElementById('dropzoneSingle'), singleInput, updateSingleList, true);
      attachDnD(document.getElementById('dropzoneBooklet'), bookletInput, updateBookletList, false);

      let overlayTimeout = null;
      form.addEventListener('submit', () => {
        overlay.classList.remove('hidden');
        if (overlayTimeout) clearTimeout(overlayTimeout);
        overlayTimeout = setTimeout(() => overlay.classList.add('hidden'), 10 * 60 * 1000);
      });

      window.addEventListener('focus', () => {
        if (!overlay.classList.contains('hidden')) setTimeout(() => overlay.classList.add('hidden'), 300);
      });

      setMode('single');
    </script>
  </body>
</html>
"""


def build_prompt(detail_level: str) -> str:
    extra = ""
    if detail_level == "simple":
        extra = "\nMake the drawing very simple with thick lines and large areas for coloring."
    elif detail_level == "detailed":
        extra = "\nKeep some extra details and textures, but still suitable for children to color."
    return BASE_PROMPT + extra


def generate_coloring_bytes(image_bytes: bytes, detail_level: str) -> bytes:
    """Kaller OpenAI image-API og returnerer PNG-bytes for fargeleggingsbildet."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = ImageOps.exif_transpose(img)

    max_dim = 1600
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "upload.png"

    prompt = build_prompt(detail_level)

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

    image_base64 = result.data[0].b64_json
    return base64.b64decode(image_base64)


def combine_side_by_side_bytes(original_bytes: bytes, coloring_bytes: bytes) -> bytes:
    """Kombinerer original + fargeleggingsbilde og returnerer PNG-bytes."""
    orig = Image.open(io.BytesIO(original_bytes)).convert("RGB")
    orig = ImageOps.exif_transpose(orig)

    col = Image.open(io.BytesIO(coloring_bytes)).convert("RGB")

    canvas_img = Image.new("RGB", (SIDE_WIDTH * 2, SIDE_HEIGHT), color=(255, 255, 255))

    def place_in_box(img: Image.Image, box_left: int):
        img_copy = img.copy()
        img_copy.thumbnail((SIDE_WIDTH, SIDE_HEIGHT), Image.LANCZOS)
        x_offset = box_left + (SIDE_WIDTH - img_copy.width) // 2
        y_offset = (SIDE_HEIGHT - img_copy.height) // 2
        canvas_img.paste(img_copy, (x_offset, y_offset))

    place_in_box(orig, box_left=0)
    place_in_box(col, box_left=SIDE_WIDTH)

    out_buf = io.BytesIO()
    canvas_img.save(out_buf, format="PNG")
    out_buf.seek(0)
    return out_buf.getvalue()


def pil_to_imagereader(img: Image.Image) -> ImageReader:
    """Robust: gi ReportLab en PNG-buffer i stedet for en 'live' PIL Image."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return ImageReader(buf)


def _pdf_page_geometry(paper: str):
    if paper not in ("A4", "A5"):
        paper = "A4"
    pagesize = A4 if paper == "A4" else A5
    page_w, page_h = pagesize

    # Marger (innbinding venstre)
    inner = 20 * mm
    outer = 12 * mm
    top = 12 * mm
    bottom = 15 * mm

    x0 = inner
    y0 = bottom
    usable_w = page_w - inner - outer
    usable_h = page_h - top - bottom
    return pagesize, (x0, y0, usable_w, usable_h)


def build_pdf_from_combo_pngs(combo_pngs: list[bytes], paper: str) -> bytes:
    """Kombosider: én side per bilde (original venstre + fargelegging høyre)."""
    pagesize, (x0, y0, usable_w, usable_h) = _pdf_page_geometry(paper)

    out = io.BytesIO()
    c = pdfcanvas.Canvas(out, pagesize=pagesize)
    c.setTitle("Fargeleggingshefte (Kombosider)")
    c.setAuthor("Fargeleggingsgenerator")

    for png_bytes in combo_pngs:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        iw, ih = img.size
        scale = min(usable_w / iw, usable_h / ih)
        tw = iw * scale
        th = ih * scale
        dx = x0 + (usable_w - tw) / 2
        dy = y0 + (usable_h - th) / 2
        c.drawImage(pil_to_imagereader(img), dx, dy, width=tw, height=th, mask="auto")
        c.showPage()

    c.save()
    out.seek(0)
    return out.getvalue()


def build_album_pdf(original_and_coloring: list[tuple[bytes, bytes]], paper: str) -> bytes:
    """Album: side 1 original (full side), side 2 fargelegging (full side) – robust image handling."""
    pagesize, (x0, y0, usable_w, usable_h) = _pdf_page_geometry(paper)

    def draw_fit(c, pil_img: Image.Image):
        pil_img = pil_img.convert("RGB")
        iw, ih = pil_img.size
        scale = min(usable_w / iw, usable_h / ih)
        tw = iw * scale
        th = ih * scale
        dx = x0 + (usable_w - tw) / 2
        dy = y0 + (usable_h - th) / 2
        c.drawImage(pil_to_imagereader(pil_img), dx, dy, width=tw, height=th, mask="auto")

    out = io.BytesIO()
    c = pdfcanvas.Canvas(out, pagesize=pagesize)
    c.setTitle("Fargeleggingshefte (Album)")
    c.setAuthor("Fargeleggingsgenerator")

    for orig_bytes, col_bytes in original_and_coloring:
        orig = Image.open(io.BytesIO(orig_bytes))
        orig = ImageOps.exif_transpose(orig)
        draw_fit(c, orig)
        c.showPage()

        col = Image.open(io.BytesIO(col_bytes))
        col = ImageOps.exif_transpose(col)
        draw_fit(c, col)
        c.showPage()

    c.save()
    out.seek(0)
    return out.getvalue()


app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE)


@app.route("/process", methods=["POST"])
def process():
    mode = request.form.get("mode", "single")
    detail = request.form.get("detail", "normal")

    if mode == "single":
        files = request.files.getlist("images")
        if not files or files[0].filename == "":
            return "Ingen filer lastet opp.", 400

        if len(files) > MAX_FILES_SINGLE:
            return (
                f"På grunn av begrensninger i serveren kan du foreløpig bare laste opp "
                f"{MAX_FILES_SINGLE} bilde om gangen.",
                400,
            )

        file = files[0]
        original_bytes = file.read()
        if not original_bytes:
            return "Ingen gyldige bilder.", 400

        try:
            coloring_bytes = generate_coloring_bytes(original_bytes, detail)
        except ValueError as e:
            if "moderation_blocked" in str(e):
                return (
                    "Bildet ditt ble stoppet av sikkerhetssystemet til OpenAI. "
                    "Prøv et annet bilde (mer klær, nøytral setting, ingen sensitive situasjoner).",
                    400,
                )
            raise

        combined_png = combine_side_by_side_bytes(original_bytes, coloring_bytes)

        stem = (file.filename or "bilde").rsplit(".", 1)[0].replace(" ", "_")
        name = f"{stem}_combo.png"

        return send_file(
            io.BytesIO(combined_png),
            mimetype="image/png",
            as_attachment=True,
            download_name=name,
        )

    if mode == "booklet":
        paper = request.form.get("paper", "A4")
        # Default album (1 bilde per side) hvis frontend ikke sender layout
        layout = request.form.get("layout", "album")

        print("PDF request:", {"paper": paper, "layout": layout}, flush=True)

        files = request.files.getlist("booklet_images")
        files = [f for f in files if f and f.filename]

        if len(files) < BOOKLET_MIN or len(files) > BOOKLET_MAX:
            return f"Last opp {BOOKLET_MIN}–{BOOKLET_MAX} bilder (du lastet opp {len(files)}).", 400

        combo_pages: list[bytes] = []
        original_and_coloring: list[tuple[bytes, bytes]] = []

        for idx, file in enumerate(files, start=1):
            original_bytes = file.read()
            if not original_bytes:
                continue

            try:
                coloring_bytes = generate_coloring_bytes(original_bytes, detail)
            except ValueError as e:
                if "moderation_blocked" in str(e):
                    return (
                        f"Et av bildene (#{idx}) ble stoppet av sikkerhetssystemet til OpenAI. "
                        "Fjern det bildet og prøv igjen.",
                        400,
                    )
                raise

            # Komboside (for valgfritt layout)
            combined_png = combine_side_by_side_bytes(original_bytes, coloring_bytes)
            combo_pages.append(combined_png)

            # Album-sider
            original_and_coloring.append((original_bytes, coloring_bytes))

        if not combo_pages:
            return "Ingen gyldige bilder.", 400

        if layout == "album":
            pdf_bytes = build_album_pdf(original_and_coloring, paper=paper)
            title = "album"
        else:
            pdf_bytes = build_pdf_from_combo_pngs(combo_pages, paper=paper)
            title = "combo"

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"fargeleggingshefte_{title}_{paper}_{stamp}.pdf"

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )

    return "Ugyldig valg.", 400


if __name__ == "__main__":
    app.run(debug=True)
