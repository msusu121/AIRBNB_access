# ocr.py
import re
from pathlib import Path
from typing import Tuple, Optional
from PIL import Image
import pytesseract
from config import Config

# Setup tesseract binary
if Config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_CMD
else:
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Kenyan IDs: 8 digits (sometimes 7–9)
RX_EXACT8 = re.compile(r"\b\d{8}\b")
RX_RUN    = re.compile(r"\b\d{7,9}\b")

CONFUSABLE = str.maketrans({
    "O":"0","o":"0","D":"0",
    "I":"1","l":"1","|":"1","!":"1",
    "S":"5","s":"5",
    "B":"8",
    "Z":"2","z":"2",
    "q":"9","g":"9"
})

def _norm(s: str) -> str:
    return s.translate(CONFUSABLE)

def _pick_id(text: str) -> Optional[str]:
    # Prefer exact 8-digit match
    m = RX_EXACT8.search(text)
    if m: return m.group(0)
    m = RX_RUN.search(text)
    if m: return m.group(0)
    return None

def extract_id_text(img_path: str) -> Tuple[str, Optional[str]]:
    # Run OCR on the whole image
    raw = pytesseract.image_to_string(Image.open(img_path), config="--oem 3 --psm 6 -l eng")
    print(raw)
    norm = _norm(raw)
    found = _pick_id(norm)

    # Save debug log
    try:
        p = Path(img_path)
        (p.parent / (p.stem + ".ocr.txt")).write_text(f"RAW:\n{raw}\nNORM:\n{norm}\nFOUND:{found}", encoding="utf-8")
    except Exception:
        pass

    return raw, found
