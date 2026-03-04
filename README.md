## Canva View Link to Single PDF

This repo contains a script that captures a **view-only Canva link** page by page
and merges all pages into one PDF file.

### 1) Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2) Run

```bash
python canva_view_to_pdf.py \
  --url "https://www.canva.com/design/.../view?..." \
  --pages 20 \
  --output my_canva_export.pdf
```

If `--pages` is omitted, the script will try to auto-detect total page count.
If auto-detection fails, pass `--pages` explicitly.

### Helpful flags

- `--wait-seconds 2.0` to wait longer before each capture (useful for slow networks).
- `--timeout-ms 90000` to increase page load timeout.
- `--headed` to run with a visible browser window for debugging.

### Notes

- You must have access to the Canva link in your browser session.
- Respect Canva Terms of Service and content licensing when exporting content.
