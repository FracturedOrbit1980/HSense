from PIL import Image, ImageDraw

from utils.image_preprocessor import preprocess_image


def test_preprocess_returns_grayscale_page():
    image = Image.new("RGB", (900, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 880, 380), outline="black", width=3)
    draw.text((40, 160), "Sealing compound - TIN", fill="black")
    prepared = preprocess_image(image, autorotate=False)
    assert prepared.mode == "L"
    assert prepared.size[0] >= 900
