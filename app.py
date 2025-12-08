import base64
import io
import zipfile
from datetime import datetime

from flask import Flask, request, send_file, render_template_string
from openai import OpenAI, BadRequestError
from PIL import Image

client = OpenAI()

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
        background-size: cover;        /* fyller hele skjermen */
        background-position: center;   /* midtstilt motiv */
        background-repeat: no-repeat;  /* ikke gjenta */
        background-attachment: fixed;  /* står stille når du scroller */
      }

      .card {
        background: rgba(255, 255, 255, 0.88); /* litt gjennomsiktig hvit */
        backdrop-filter: blur(10px);           /* glass-effekt */
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
        margin: 0 0 1.2rem 0;
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
      .dropzone input[type="file"] {
        display: none;
      }
      .dropzone-title {
        font-weight: 600;
        margin-bottom: 0.3rem;
      }
      .dropzone-sub {
        font-size: 0.9rem;
        color: #6b7280;
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

      /* Loading overlay + "progressbar" */
      .loading-overlay {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.55);
        display: none; /* skjult som default */
        align-items: center;
        justify-content: center;
        z-index: 50;
      }
      .loading-box {
        background: white;
        padding: 1.25rem 1.75rem;
        border-radius: 0.9rem;
        box-shadow: 0 18px 40px rgba(15,23,42,0.4);
        max-width: 320px;
        width: 90%;
        text-align: center;
      }
      .loading-text {
        font-size: 0.95rem;
        margin-bottom: 0.75rem;
        color: #374151;
      }
      .loading-bar {
        width: 100%;
        height: 6px;
        border-radius: 999px;
        background: #e5e7eb;
        overflow: hidden;
      }
      .loading-bar-inner {
        width: 40%;
        height: 100%;
        border-radius: 999px;
        background: #4f46e5;
        animation: loading-pulse 1.2s infinite ease-in-out;
      }
      @keyframes loading-pulse {
        0% {
          transform: translateX(-100%);
        }
        50% {
          transform: translateX(50%);
        }
        100% {
          transform: translateX(200%);
        }
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
          <input id="file-input" type="file" name="images" accept="image/*" multiple>
          <div class="dropzone-title">Slipp bilder her</div>
          <div class="dropzone-sub">eller klikk for å velge (du kan velge flere)</div>
        </label>

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
          Hvis du laster opp flere bilder samtidig, får du en ZIP-fil med ett resultat per bilde.
        </p>
      </form>

      <div class="footer">
        Bildene sendes til OpenAI for å generere tegningen, men lagres ikke permanent på serveren.
      </div>
    </div>

    <div id="loading-overlay" class="loading-overlay">
      <div class="loading-box">
        <div class="loading-text">Genererer fargeleggingsark, vennligst vent…</div>
        <div class="loading-bar">
          <div class="loading-bar-inner"></div>
        </div>
      </div>
    </div>

    <script>
      const dropzone = document.getElementById('dropzone');
      const fileInput = document.getElementById('file-input');
      const form = document.getElementById('form');
      const loadingOverlay = document.getElementById('loading-overlay');
      const submitButton = document.querySelector('#form button[type="submit"]');

      dropzone.addEventListener('click', () => fileInput.click());

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
        fileInput.files = files;
      });

      if (form) {
        form.addEventListener('submit', () => {
          if (loadingOverlay) {
            loadingOverlay.style.display = 'flex';
          }
          if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = "Genererer...";
          }
        });
      }
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

    detail = request.form.get("detail", "normal")

    results = []

    for file in files:
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

    if len(results) == 1:
        name, data = results[0]
        return send_file(
            io.BytesIO(data),
            mimetype="image/png",
            as_attachment=True,
            download_name=name,
        )

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in results:
            zf.writestr(name, data)
    zip_buf.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"fargeleggingsark_{timestamp}.zip"

    return send_file(
        zip_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_name,
    )


if __name__ == "__main__":
    app.run(debug=True)
