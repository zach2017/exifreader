#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Build Tesseract + Poppler Lambda Layer on Amazon Linux 2
#  Output: /out/layer.zip
# ─────────────────────────────────────────────────────────────
set -euo pipefail

echo "╔══════════════════════════════════════════════╗"
echo "║  Building Tesseract Lambda Layer (AL2)       ║"
echo "╚══════════════════════════════════════════════╝"

# ── Install everything we need ──
echo "→ Installing packages..."
yum install -y \
    which \
    findutils \
    zip \
    > /dev/null 2>&1

echo "→ Enabling EPEL..."
amazon-linux-extras install epel -y > /dev/null 2>&1

echo "→ Installing tesseract + poppler..."
yum install -y \
    tesseract \
    tesseract-langpack-eng \
    poppler-utils \
    > /dev/null 2>&1

# ── Verify installs ──
TESS_BIN=$(command -v tesseract 2>/dev/null || true)
PDFTOPPM_BIN=$(command -v pdftoppm 2>/dev/null || true)

if [ -z "$TESS_BIN" ]; then
    echo "✗ tesseract not found after install!"
    exit 1
fi
echo "  tesseract: $TESS_BIN → $(tesseract --version 2>&1 | head -1)"

if [ -z "$PDFTOPPM_BIN" ]; then
    echo "⚠ pdftoppm not found (poppler-utils may have failed)"
else
    echo "  pdftoppm:  $PDFTOPPM_BIN"
fi

# ── Create layer directory structure ──
LAYER="/tmp/layer"
mkdir -p "${LAYER}/bin" "${LAYER}/lib" "${LAYER}/share/tessdata"

# ── Copy binaries ──
echo "→ Copying binaries..."
cp "$TESS_BIN" "${LAYER}/bin/"
[ -n "$PDFTOPPM_BIN" ] && cp "$PDFTOPPM_BIN" "${LAYER}/bin/"

PDFTOTEXT_BIN=$(command -v pdftotext 2>/dev/null || true)
[ -n "$PDFTOTEXT_BIN" ] && cp "$PDFTOTEXT_BIN" "${LAYER}/bin/"

echo "  ✓ bin/: $(ls ${LAYER}/bin/)"

# ── Copy tessdata ──
echo "→ Copying tessdata..."
TESS_DATA=$(find /usr/share -name "eng.traineddata" -type f 2>/dev/null | head -1)
if [ -z "$TESS_DATA" ]; then
    echo "✗ eng.traineddata not found!"
    find /usr/share/tesseract* -type f 2>/dev/null || true
    exit 1
fi
TESS_DIR=$(dirname "$TESS_DATA")
cp "${TESS_DIR}/eng.traineddata" "${LAYER}/share/tessdata/"
[ -f "${TESS_DIR}/osd.traineddata" ] && \
    cp "${TESS_DIR}/osd.traineddata" "${LAYER}/share/tessdata/" || true
echo "  ✓ tessdata: $(ls ${LAYER}/share/tessdata/)"

# ── Copy shared libraries ──
echo "→ Resolving shared libraries..."
SKIP_RE="linux-vdso|ld-linux|libpthread|libdl\.so|librt\.so|libm\.so|libc\.so|libgcc_s|libstdc\+\+"

copy_libs_for() {
    local bin="$1"
    [ ! -f "$bin" ] && return
    ldd "$bin" 2>/dev/null | grep "=> /" | awk '{print $3}' | while read -r lib; do
        local base
        base=$(basename "$lib")
        # Skip libs already in the Lambda base image
        if echo "$base" | grep -qE "$SKIP_RE"; then
            continue
        fi
        # Skip if already copied
        if [ -f "${LAYER}/lib/${base}" ]; then
            continue
        fi
        cp -L "$lib" "${LAYER}/lib/" 2>/dev/null || true
    done
}

copy_libs_for "$TESS_BIN"
[ -n "$PDFTOPPM_BIN" ] && copy_libs_for "$PDFTOPPM_BIN"

LIB_COUNT=$(ls "${LAYER}/lib/" | wc -l)
echo "  ✓ ${LIB_COUNT} libraries copied"
ls -1 "${LAYER}/lib/" | head -15
[ "$LIB_COUNT" -gt 15 ] && echo "  ... and more"

# ── Create zip ──
echo "→ Creating layer.zip..."
cd "${LAYER}"
zip -r9 /out/layer.zip . > /dev/null 2>&1

echo ""
echo "════════════════════════════════════════════════"
echo "  ✓ Layer zip: $(du -sh /out/layer.zip | cut -f1)"
echo "  bin/:          $(ls bin/)"
echo "  lib/:          ${LIB_COUNT} shared libraries"
echo "  share/tessdata: $(ls share/tessdata/)"
echo "════════════════════════════════════════════════"
