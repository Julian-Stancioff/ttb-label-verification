"""Generate synthetic alcohol-label test images + an application manifest.

These are deterministic fixtures for testing the verifier end-to-end. Run:
    python samples/generate_samples.py
Produces samples/images/*.png and samples/applications.json.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
IMG_DIR = HERE / "images"
IMG_DIR.mkdir(exist_ok=True)

CANONICAL = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_label(filename: str, *, brand: str, klass: str, abv: str, net: str,
               producer: str, warning: str) -> None:
    W, H = 800, 1100
    img = Image.new("RGB", (W, H), "#f6f1e7")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, W - 20, H - 20], outline="#3a2f1b", width=6)

    def center(text: str, y: int, font, fill="#2a2113") -> None:
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y), text, font=font, fill=fill)

    center(brand, 90, _font(54))
    center(klass, 200, _font(30))
    d.line([120, 270, W - 120, 270], fill="#7a6c4a", width=2)
    center(abv, 330, _font(34))
    center(net, 400, _font(28))
    center(producer, 470, _font(22), fill="#5a4d2e")

    # Government warning block (small print, like a real label).
    wy = 760
    wfont = _font(19)
    for line in textwrap.wrap(warning, width=70):
        d.text((70, wy), line, font=wfont, fill="#1a1a1a")
        wy += 26

    img.save(IMG_DIR / filename)
    print("wrote", filename)


SAMPLES = [
    # (filename, fields..., expected application, note)
    dict(
        filename="01_pass_old_tom.png",
        brand="OLD TOM DISTILLERY", klass="Kentucky Straight Bourbon Whiskey",
        abv="45% Alc./Vol. (90 Proof)", net="750 mL",
        producer="Bottled by Old Tom Distillery, Bardstown, KY",
        warning=CANONICAL,
        application={"brand_name": "Old Tom Distillery",
                     "class_type": "Kentucky Straight Bourbon Whiskey",
                     "alcohol_content": "45% Alc./Vol.", "net_contents": "750 mL"},
    ),
    dict(
        filename="02_pass_stones_throw.png",
        brand="STONE'S THROW", klass="Straight Rye Whiskey",
        abv="50% Alc./Vol. (100 Proof)", net="750 mL",
        producer="Stone's Throw Distilling Co., Louisville, KY",
        warning=CANONICAL,
        # Application uses title case + curly apostrophe -> should still PASS (judgment).
        application={"brand_name": "Stone’s Throw", "alcohol_content": "50%",
                     "class_type": "Straight Rye Whiskey"},
    ),
    dict(
        filename="03_fail_titlecase_warning.png",
        brand="RIVERBEND RESERVE", klass="Blended Whiskey",
        abv="40% Alc./Vol. (80 Proof)", net="750 mL",
        producer="Riverbend Spirits, Cincinnati, OH",
        # Cheat: header in Title Case instead of ALL CAPS -> must FAIL.
        warning=CANONICAL.replace("GOVERNMENT WARNING:", "Government Warning:"),
        application={"brand_name": "Riverbend Reserve", "alcohol_content": "40%"},
    ),
    dict(
        filename="04_fail_abv_mismatch.png",
        brand="HARBOR LIGHT GIN", klass="London Dry Gin",
        abv="47% Alc./Vol. (94 Proof)", net="750 mL",
        producer="Harbor Light Distillers, Portland, ME",
        warning=CANONICAL,
        # Application ABV disagrees with label -> must FAIL on ABV.
        application={"brand_name": "Harbor Light Gin", "alcohol_content": "40% Alc./Vol."},
    ),
    dict(
        filename="05_fail_paraphrased_warning.png",
        brand="SUMMIT VODKA", klass="Vodka",
        abv="40% Alc./Vol. (80 Proof)", net="1 L",
        producer="Summit Beverage Co., Denver, CO",
        # Cheat: paraphrased warning -> must FAIL.
        warning=CANONICAL.replace("birth defects", "birth problems"),
        application={"brand_name": "Summit Vodka", "alcohol_content": "40%"},
    ),
]


def main() -> None:
    manifest = []
    for s in SAMPLES:
        make_label(
            s["filename"], brand=s["brand"], klass=s["klass"], abv=s["abv"],
            net=s["net"], producer=s["producer"], warning=s["warning"],
        )
        app = dict(s["application"])
        app["filename"] = s["filename"]
        manifest.append(app)
    (HERE / "applications.json").write_text(json.dumps(manifest, indent=2))
    print("wrote applications.json with", len(manifest), "entries")


if __name__ == "__main__":
    main()
