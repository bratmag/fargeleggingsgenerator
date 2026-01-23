def build_album_pdf(original_and_coloring: list[tuple[bytes, bytes]], paper: str) -> bytes:
    if paper not in ("A4", "A5"):
        paper = "A4"

    pagesize = A4 if paper == "A4" else A5
    page_w, page_h = pagesize

    inner = 20 * mm
    outer = 12 * mm
    top = 12 * mm
    bottom = 15 * mm

    x0 = inner
    y0 = bottom
    usable_w = page_w - inner - outer
    usable_h = page_h - top - bottom

    def draw_fit(c, pil_img: Image.Image):
        pil_img = pil_img.convert("RGB")
        iw, ih = pil_img.size
        scale = min(usable_w / iw, usable_h / ih)
        tw = iw * scale
        th = ih * scale
        dx = x0 + (usable_w - tw) / 2
        dy = y0 + (usable_h - th) / 2
        c.drawImage(ImageReader(pil_img), dx, dy, width=tw, height=th, mask="auto")

    out = io.BytesIO()
    c = pdfcanvas.Canvas(out, pagesize=pagesize)
    c.setTitle("Fargeleggingshefte (Album)")
    c.setAuthor("Fargeleggingsgenerator")

    for orig_bytes, col_bytes in original_and_coloring:
        # Side 1: original (farger beholdes)
        orig = Image.open(io.BytesIO(orig_bytes))
        orig = ImageOps.exif_transpose(orig)
        draw_fit(c, orig)
        c.showPage()

        # Side 2: fargeleggingsbilde
        col = Image.open(io.BytesIO(col_bytes))
        draw_fit(c, col)
        c.showPage()

    c.save()
    out.seek(0)
    return out.getvalue()
