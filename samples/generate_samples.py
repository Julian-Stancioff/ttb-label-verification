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
    # ---- extra batch fixtures (varied beverage types & cases) ----
    dict(
        filename="06_pass_harvest_moon_wine.png",
        brand="HARVEST MOON CELLARS", klass="Napa Valley Cabernet Sauvignon",
        abv="13.5% Alc./Vol.", net="750 mL",
        producer="Harvest Moon Cellars, Napa, CA", warning=CANONICAL,
        application={"brand_name": "Harvest Moon Cellars",
                     "class_type": "Napa Valley Cabernet Sauvignon",
                     "alcohol_content": "13.5% Alc./Vol."},
    ),
    dict(
        filename="07_pass_iron_anchor_ipa.png",
        brand="IRON ANCHOR BREWING", klass="India Pale Ale",
        abv="6.8% Alc./Vol.", net="12 FL OZ",
        producer="Iron Anchor Brewing Co., San Diego, CA", warning=CANONICAL,
        application={"brand_name": "Iron Anchor Brewing", "alcohol_content": "6.8%"},
    ),
    dict(
        filename="08_pass_palm_cove_rum.png",
        brand="PALM COVE RUM", klass="Aged Caribbean Rum",
        abv="40% Alc./Vol. (80 Proof)", net="750 mL",
        producer="Palm Cove Distillers, Miami, FL", warning=CANONICAL,
        application={"brand_name": "Palm Cove Rum", "alcohol_content": "40%"},
    ),
    dict(
        filename="09_pass_agave_and_oak_tequila.png",
        brand="AGAVE & OAK", klass="Tequila Reposado",
        abv="38% Alc./Vol.", net="750 mL",
        producer="Agave & Oak S.A., Jalisco, Mexico", warning=CANONICAL,
        # Application writes "and" instead of "&" -> judgment should still PASS.
        application={"brand_name": "Agave and Oak", "alcohol_content": "38%"},
    ),
    dict(
        filename="10_fail_missing_warning.png",
        brand="MIDNIGHT OAK WHISKEY", klass="Tennessee Whiskey",
        abv="43% Alc./Vol. (86 Proof)", net="750 mL",
        producer="Midnight Oak Distillery, Lynchburg, TN",
        warning="",  # No government warning at all -> must FAIL.
        application={"brand_name": "Midnight Oak Whiskey", "alcohol_content": "43%"},
    ),
    dict(
        filename="11_fail_brand_mismatch.png",
        brand="SILVER PEAK GIN", klass="London Dry Gin",
        abv="44% Alc./Vol.", net="750 mL",
        producer="Silver Peak Distilling, Boise, ID", warning=CANONICAL,
        # Genuinely different brand on the application -> must FAIL.
        application={"brand_name": "Golden Peak Gin", "alcohol_content": "44%"},
    ),
    dict(
        filename="12_fail_abv_wine.png",
        brand="CEDAR RIDGE VINEYARDS", klass="Oregon Pinot Noir",
        abv="14.1% Alc./Vol.", net="750 mL",
        producer="Cedar Ridge Vineyards, Willamette, OR", warning=CANONICAL,
        application={"brand_name": "Cedar Ridge Vineyards",
                     "alcohol_content": "12.5% Alc./Vol."},  # ABV disagrees -> FAIL.
    ),
    dict(
        filename="13_fail_warning_missing_part2.png",
        brand="BLUE HERON VODKA", klass="Vodka",
        abv="40% Alc./Vol.", net="750 mL",
        producer="Blue Heron Spirits, Portland, OR",
        # Only clause (1) of the warning -> incomplete -> must FAIL.
        warning=("GOVERNMENT WARNING: (1) According to the Surgeon General, women "
                 "should not drink alcoholic beverages during pregnancy because of "
                 "the risk of birth defects."),
        application={"brand_name": "Blue Heron Vodka", "alcohol_content": "40%"},
    ),
    dict(
        filename="14_pass_copper_kettle_bourbon.png",
        brand="COPPER KETTLE BOURBON", klass="Kentucky Straight Bourbon Whiskey",
        abv="46% Alc./Vol. (92 Proof)", net="750 mL",
        producer="Copper Kettle Distillery, Frankfort, KY", warning=CANONICAL,
        application={"brand_name": "Copper Kettle Bourbon", "alcohol_content": "46%",
                     "net_contents": "750 mL"},
    ),
    dict(
        filename="15_fail_titlecase_brandy.png",
        brand="GOLDEN VALLEY BRANDY", klass="California Brandy",
        abv="40% Alc./Vol.", net="750 mL",
        producer="Golden Valley Spirits, Fresno, CA",
        # Header in Title Case instead of ALL CAPS -> must FAIL.
        warning=CANONICAL.replace("GOVERNMENT WARNING:", "Government Warning:"),
        application={"brand_name": "Golden Valley Brandy", "alcohol_content": "40%"},
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
