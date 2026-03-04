#!/usr/bin/env python3
"""Download a view-only Canva design and export pages into one PDF.

This script automates the browser with Playwright, opens each Canva page by hash
(e.g. #1, #2, ...), captures the largest visible design surface, and merges all
captures into a single PDF.

Usage example:
    python canva_view_to_pdf.py \
      --url "https://www.canva.com/design/.../view?..." \
      --pages 24 \
      --output design.pdf
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


def _import_or_exit() -> tuple[object, object]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print(
            "Missing dependency: playwright\n"
            "Install with: pip install playwright pillow\n"
            "Then install browser binaries once with: playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(2)

    try:
        from PIL import Image
    except Exception:
        print(
            "Missing dependency: pillow\n"
            "Install with: pip install pillow",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return sync_playwright, Image


def _strip_hash(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _parse_total_pages_from_text(text: str) -> Optional[int]:
    # Common patterns in viewers: "3 / 24" or "3 of 24"
    patterns = [r"\b\d+\s*/\s*(\d+)\b", r"\b\d+\s+of\s+(\d+)\b"]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _guess_total_pages(page) -> Optional[int]:
    # Try a few places where viewers expose page counts.
    selectors = [
        "[aria-label*=' / ']",
        "[aria-label*=' of ']",
        "[data-testid*='page']",
        "footer",
    ]
    for sel in selectors:
        try:
            text = "\n".join(page.locator(sel).all_inner_texts())
        except Exception:
            continue
        total = _parse_total_pages_from_text(text)
        if total:
            return total

    # Fallback: inspect visible body text.
    try:
        body_text = page.inner_text("body")
    except Exception:
        return None
    return _parse_total_pages_from_text(body_text)


def _capture_page_image(page, output_path: Path, wait_seconds: float) -> bool:
    # Let fonts/graphics settle for a cleaner capture.
    time.sleep(wait_seconds)

    # Prefer the design surface in the middle of the viewer, not left thumbnails.
    selector = "canvas,img,svg"
    best = page.locator(selector).evaluate_all(
        """
        (elements) => {
          const viewportWidth = window.innerWidth || 1;
          const viewportHeight = window.innerHeight || 1;

          const getCandidate = (element, index) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            const visible = rect.width > 250 &&
                            rect.height > 250 &&
                            style.visibility !== 'hidden' &&
                            style.display !== 'none' &&
                            style.opacity !== '0';
            if (!visible) return null;

            const area = rect.width * rect.height;
            const centerX = rect.x + rect.width / 2;
            const centerY = rect.y + rect.height / 2;
            const dx = Math.abs(centerX - viewportWidth / 2) / viewportWidth;
            const dy = Math.abs(centerY - viewportHeight / 2) / viewportHeight;
            const centralityPenalty = area * (dx * 0.45 + dy * 0.15);

            // Canva thumbnails are usually in the left rail. Penalize those heavily.
            const leftRailPenalty = rect.x < viewportWidth * 0.18 ? area * 0.8 : 0;

            return { index, score: area - centralityPenalty - leftRailPenalty };
          };

          let best = null;
          for (let i = 0; i < elements.length; i += 1) {
            const candidate = getCandidate(elements[i], i);
            if (!candidate) continue;
            if (!best || candidate.score > best.score) best = candidate;
          }
          return best;
        }
        """
    )

    if best and isinstance(best.get("index"), int):
        page.locator(selector).nth(best["index"]).screenshot(path=str(output_path))
        return True

    page.screenshot(path=str(output_path), full_page=True)
    return False


def convert_canva_to_pdf(
    url: str,
    output: Path,
    pages: Optional[int],
    wait_seconds: float,
    timeout_ms: int,
    headless: bool,
) -> None:
    sync_playwright, Image = _import_or_exit()
    base_url = _strip_hash(url)

    with tempfile.TemporaryDirectory(prefix="canva-capture-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        png_files: list[Path] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()

            page.goto(f"{base_url}#1", wait_until="networkidle", timeout=timeout_ms)
            time.sleep(wait_seconds)

            total_pages = pages or _guess_total_pages(page)
            if not total_pages:
                raise RuntimeError(
                    "Could not auto-detect total pages. Re-run with --pages <N>."
                )

            print(f"Capturing {total_pages} page(s)...")
            for i in range(1, total_pages + 1):
                target = f"{base_url}#{i}"
                page.goto(target, wait_until="networkidle", timeout=timeout_ms)
                out_png = tmpdir_path / f"page_{i:04d}.png"
                used_crop = _capture_page_image(page, out_png, wait_seconds=wait_seconds)
                png_files.append(out_png)
                mode = "design-crop" if used_crop else "full-page"
                print(f"  - Page {i}/{total_pages} ({mode})")

            context.close()
            browser.close()

        if not png_files:
            raise RuntimeError("No pages were captured.")

        images = []
        for pth in png_files:
            img = Image.open(pth).convert("RGB")
            images.append(img)

        first, rest = images[0], images[1:]
        output.parent.mkdir(parents=True, exist_ok=True)
        first.save(output, save_all=True, append_images=rest)

        for img in images:
            img.close()

    print(f"Done. PDF saved to: {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a view-only Canva design page-by-page and merge into one PDF."
        )
    )
    parser.add_argument("--url", required=True, help="Public Canva view URL")
    parser.add_argument(
        "--output", "-o", default="canva_export.pdf", help="Output PDF file path"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Total page count. If omitted, script attempts auto-detection.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=1.5,
        help="Extra wait after page load before screenshotting (default: 1.5)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
        help="Navigation timeout in milliseconds (default: 60000)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in visible (non-headless) mode for debugging.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.pages is not None and args.pages < 1:
        print("--pages must be >= 1", file=sys.stderr)
        return 2

    try:
        convert_canva_to_pdf(
            url=args.url,
            output=Path(args.output),
            pages=args.pages,
            wait_seconds=args.wait_seconds,
            timeout_ms=args.timeout_ms,
            headless=not args.headed,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
