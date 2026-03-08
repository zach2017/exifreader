#!/usr/bin/env python3
"""
PDF Image Extractor CLI
Extracts all images from a PDF file and saves them to a directory.

Dependencies:
    pip install pymupdf

Usage:
    python extract_pdf_images.py input.pdf
    python extract_pdf_images.py input.pdf -o ./my_images
    python extract_pdf_images.py input.pdf -o ./my_images --min-size 100
"""

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF


EXTENSION_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
}


def extract_images(pdf_path: str, output_dir: str, min_size: int = 0) -> list[Path]:
    """Extract all images from a PDF and save them to output_dir.

    Args:
        pdf_path:   Path to the input PDF file.
        output_dir: Directory where extracted images will be saved.
        min_size:   Minimum width/height in pixels to keep an image (default 0 = keep all).

    Returns:
        List of Path objects for every saved image.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    saved: list[Path] = []
    img_count = 0

    print(f"\n📄  Opened: {pdf_path.name}  ({len(doc)} page{'s' if len(doc) != 1 else ''})")
    print(f"📂  Output: {output_dir.resolve()}\n")

    for page_num in range(len(doc)):
        page = doc[page_num]
        images = page.get_images(full=True)

        if not images:
            continue

        for img_index, img_info in enumerate(images):
            xref = img_info[0]

            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            if not base_image:
                continue

            width = base_image["width"]
            height = base_image["height"]

            if width < min_size or height < min_size:
                continue

            img_bytes = base_image["image"]
            mime = base_image.get("ext", "png")
            ext = f".{mime}"

            img_count += 1
            filename = f"page{page_num + 1}_img{img_index + 1}_{width}x{height}{ext}"
            filepath = output_dir / filename

            filepath.write_bytes(img_bytes)
            saved.append(filepath)

            size_kb = len(img_bytes) / 1024
            print(
                f"  ✅  [{img_count:>3}]  Page {page_num + 1:<4}  "
                f"{width:>5} x {height:<5}  "
                f"{size_kb:>8.1f} KB  →  {filename}"
            )

    doc.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract images from a PDF and save them to a directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python extract_pdf_images.py report.pdf\n"
               "  python extract_pdf_images.py report.pdf -o ./images\n"
               "  python extract_pdf_images.py report.pdf --min-size 200\n",
    )
    parser.add_argument("pdf", help="Path to the input PDF file")
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output directory (default: <pdf_name>_images/)",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=0,
        help="Minimum image width/height in px to extract (default: 0 = all)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"❌  File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output or f"{pdf_path.stem}_images"
    saved = extract_images(str(pdf_path), output_dir, args.min_size)

    print(f"\n{'─' * 60}")
    if saved:
        print(f"🎉  Done! Extracted {len(saved)} image{'s' if len(saved) != 1 else ''}.")
    else:
        print("⚠️   No images found in the PDF.")
    print()


if __name__ == "__main__":
    main()
