import base64
import io
import zipfile
from datetime import datetime

from flask import Flask, request, send_file, render_template_string
from openai import OpenAI, BadRequestError
from PIL import Image, ImageOps

client = OpenAI()

# Hvor mange bilder som tillates per kjøring (Render sliter over 1)
MAX_FILES = 1

# Standard størrelse på hver "side" (original / fargelegging)
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
      :root {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #0f172a;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        padding: 2rem 1rem;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;

        /* Bakgrunnsbildet ditt */
        background-image: url('/static/background-kids.png');
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-attachment: fixed;
      }

      .card {
        background: rgba(255, 255, 255, 0.88);
        backdrop-filter: blur(10px);
        padding: 2rem 2.5rem;
        border-radius: 1.25rem;
        box-shadow: 0 18px 40px rgba(15,23,42,0.25);
        max-width: 720px;
        width: 100%;
      }

      h1 {
        margin: 0 0 0.35rem 0;
        font-size: 1.8rem;
      }
      .sub {
        margin: 0 0 1.2rem 0;
        color: #6b7280;
        font-size: 0.95rem;
        line-height: 1.5;
      }

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
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
      }
      .dropzone.dragover {
        background: #eef2ff;
        border-color: #4f46e5;
        box-shadow: 0 0 0 2px rgba(79,70,229,0.3);
      }

      /* Filinput er "usynlig", men label-click åpner dialogen */
      .dropzone input[type="file"] {
        position: absolute;
        inset: 0;
        opacity: 0;
        cursor: pointer;
      }

      .dropzone-title {
        font-weight: 600;
        margin-bottom: 0.3rem;
        pointer-events: none;
      }
      .dropzone-sub {
        font-size: 0.9rem;
        color: #6b7280;
        pointer-events: none;
      }

      .file-list {
        margin: 0 0 1.0rem 0;
        font-size: 0.8rem;
        color: #4b5563;
        text-align: left;
      }
      .file-list-empty {
        color: #9ca3af;
      }

      .controls-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
      }
      .control-group {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.9rem;
        color: #374151;
      }
      select {
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        border: 1px solid #d1d5db;
        font-size: 0.9rem;
        background: #f9fafb;
      }
      button {
        background: #4f46e5;
        color: white;
        border: none;
        border-radius: 999px;
        padding: 0.65rem 1.5rem;
        font-size: 0.95rem;
        cursor: pointer;
        white-space: nowrap;
      }
      button:hover {
        background: #4338ca;
      }
      .hint {
        margin-top: 0.9rem;
        font-size: 0.8rem;
        color: #6b7280;
      }
      .footer {
        margin-top: 1.2rem;
        font-size: 0.75rem;
        color: #9ca3af;
      }

      /* Overlay for "genererer..." */
      .overlay {
        position: fixed;
        inset: 0;
        background: rgba(15,23,42,0.55);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 50;
      }
      .overlay.hidden {
        display: none;
      }
      .overlay-box {
        background: #ffffff;
        padding: 1.5rem 1.75rem;
        border-radius: 0.9rem;
        box-shadow: 0 18px 40px rgba(15,23,42,0.3);
        max-width: 320px;
        text-align: center;
        font-size: 0.95rem;
      }
      .loader {
        width: 36px;
        height: 36px;
        border-radius: 999px;
        border: 3px solid #e5e7eb;
        border-top-color: #4f46e5;
        animation: spin 0.9s linear infinite;
        margin: 0 auto 0.9rem auto;
      }
      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      @media (max-width: 600px) {
        .card {
          padding: 1.5rem 1.25rem;
        }
        .controls-row {
          flex-direction: column;
          align-items: stretch;
        }
        button {
          width: 100%;
          text-align: center;
          justify-content: center;
        }
        .file-list {
          text-align: center;
        }
      }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Fargeleggingsgenerator</h1>
      <p class="sub">
        Last opp dine bilder og få det kombinert med et fargeleggingsark.
      </p>

      <form id="form" action="/process" method="post" enctype="multipart/form-data">
        <label class="dropzone" id="dropzone">
          <input id="file-input" type="file" name="images" accept="image/*">
          <div class="dropzone-title">Slipp ett bilde her</div>
          <div class="dropzone-sub">eller klikk for å velge ett bilde</div>
        </label>

        <div id="file-list" class="file-list file-list-empty">
          Ingen filer valgt ennå.
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
          <button type="submit">Generer fargeleggingsark</button>
        </div>

        <p class="hint">
          Foreløpig støttes ett bilde om gangen. Større opplastinger kan gjøre at serveren stopper.
        </p>
      </form>

      <div class="footer">
        Bildene sendes til OpenAI for å generere tegningen, men lagres ikke permanent på serveren.
      </div>
    </div>

    <!-- Overlay som vises mens generering pågår -->
    <div id="overlay" class="overlay hidden">
      <div class="overlay-box">
        <div class="loader"></div>
        <div>Genererer fargeleggingsark …</div>
        <div style="font-size:0.8rem; color:#6b7280; margin-top:0.4rem;">
          Dette kan ta opptil et par minutter.
        </div>
      </div>
    </div>

    <script>
      const dropzone = document.getElementById('dropzone');
      const fileInput = document.getElementById('file-input');
      const fileList = document.getElementById('file-list');
      const form = document.getElementById('form');
      const overlay = document.getElementById('overlay');

      function updateFileList(files) {
        if (!files || files.length === 0) {
          fileList.textContent = 'Ingen filer valgt ennå.';
          fileList.classList.add('file-list-empty');
          return;
        }
        fileList.classList.remove('file-list-empty');

        // vi forventer maks 1 fil
        fileList.textContent = `Valgt fil: ${files[0].name}`;
      }

      fileInput.addEventListener('change', () => {
        updateFileList(fileInput.files);
      });

      dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });

      dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
      });

      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        // tar bare første fil
        if (files && files.length > 0) {
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(files[0]);
          fileInput.files = dataTransfer.files;
          updateFileList(fileInput.files);
        }
      });

      // Vis overlay når vi sender inn skjemaet
      let overlayTimeout = null;
      form.addEventListener('submit', () => {
        overlay.classList.remove('hidden');
        // failsafe: skjul etter 5 minutter uansett
        if (overlayTimeout) clearTimeout(overlayTimeout);
        overlayTimeout = setTimeout(() => {
          overlay.classList.add('hidden');
        }, 5 * 60 * 1000);
      });

      // Når vinduet får fokus igjen etter nedlasting, skjul overlay
      window.addEventListener('focus', () => {
        if (!overlay.classList.contains('hidden')) {
          setTimeout(() => overlay.classList.add('hidden'), 300);
        }
      });
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
    # respekter EXIF-orientering (slik mobilen viser bildet)
    img = ImageOps.exif_transpose(img)

    # nedskalere veldig store bilder for å spare minne og tid
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
        # OpenAI safety/moderation blokkerte bildet
        if "moderation_blocked" in str(e):
            raise ValueError("moderation_blocked")
        raise

    image_base64 = result.data[0].b64_json
    return base64.b64decode(image_base64)


def combine_side_by_side_bytes(original_bytes: bytes, coloring_bytes: bytes) -> bytes:
    """Kombinerer original + fargeleggingsbilde og returnerer PNG-bytes."""
    orig = Image.open(io.BytesIO(original_bytes)).convert("RGB")
    # EXIF-orientering på originalen i kombobildet
    orig = ImageOps.exif_transpose(orig)

    col = Image.open(io.BytesIO(coloring_bytes)).convert("RGB")

    canvas = Image.new("RGB", (SIDE_WIDTH * 2, SIDE_HEIGHT), color=(255, 255, 255))

    def place_in_box(img: Image.Image, box_left: int):
        img_copy = img.copy()
        img_copy.thumbnail((SIDE_WIDTH, SIDE_HEIGHT), Image.LANCZOS)
        x_offset = box_left + (SIDE_WIDTH - img_copy.width) // 2
        y_offset = (SIDE_HEIGHT - img_copy.height) // 2
        canvas.paste(img_copy, (x_offset, y_offset))

    place_in_box(orig, box_left=0)
    place_in_box(col, box_left=SIDE_WIDTH)

    out_buf = io.BytesIO()
    canvas.save(out_buf, format="PNG")
    out_buf.seek(0)
    return out_buf.getvalue()


app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE)


@app.route("/process", methods=["POST"])
def process():
    files = request.files.getlist("images")
    if not files or files[0].filename == "":
        return "Ingen filer lastet opp.", 400

    # håndter for mange filer (burde egentlig ikke skje, siden UI bare lar deg velge ett)
    if len(files) > MAX_FILES:
        return (
            f"På grunn av begrensninger i serveren kan du foreløpig bare laste opp "
            f"{MAX_FILES} bilde om gangen.",
            400,
        )

    detail = request.form.get("detail", "normal")

    results = []

    for file in files[:MAX_FILES]:
        original_bytes = file.read()
        if not original_bytes:
            continue

        try:
            coloring_bytes = generate_coloring_bytes(original_bytes, detail)
        except ValueError as e:
            if "moderation_blocked" in str(e):
                return (
                    "Bildet ditt ble stoppet av sikkerhetssystemet til OpenAI. "
                    "Prøv et annet bilde (mer klær, nøytral setting, ingen sensitive situasjoner).",
                    400,
                )
            else:
                raise

        combined_png = combine_side_by_side_bytes(original_bytes, coloring_bytes)

        stem = (file.filename or "bilde").rsplit(".", 1)[0].replace(" ", "_")
        results.append((f"{stem}_combo.png", combined_png))

    if not results:
        return "Ingen gyldige bilder.", 400

    # siden vi bare støtter ett bilde, blir dette alltid én fil
    name, data = results[0]
    return send_file(
        io.BytesIO(data),
        mimetype="image/png",
        as_attachment=True,
        download_name=name,
    )


if __name__ == "__main__":
    app.run(debug=True)
