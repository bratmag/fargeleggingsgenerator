import io
import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from PIL import Image

import app


class ImageHelperTests(unittest.TestCase):
    def test_sanitize_stem_keeps_safe_filename(self):
        self.assertEqual(app.sanitize_stem("Min fine fil!.jpg"), "Min-fine-fil")

    def test_invalid_image_bytes_are_rejected(self):
        with self.assertRaises(ValueError):
            app.pil_image_from_bytes(b"not an image")

    def test_valid_png_loads_as_rgb(self):
        buf = io.BytesIO()
        Image.new("RGBA", (10, 10), (255, 255, 255, 255)).save(buf, format="PNG")

        loaded = app.pil_image_from_bytes(buf.getvalue())

        self.assertEqual(loaded.mode, "RGB")
        self.assertEqual(loaded.size, (10, 10))
        loaded.close()


if __name__ == "__main__":
    unittest.main()
