from pathlib import Path

p = Path('LumaPDF_RazrFold_2026_v02/app/src/main/java/com/tstudio/lumapdf/editor/MuPdfEngine.kt')
s = p.read_text()
start = s.index('    private fun textProbeKey')
end = s.index('    fun close()', start)
block = s[start:end]
# patch_v042.py stores the helper in a Python raw string. Normalize only that generated
# helper block to Kotlin source escapes; do not touch the rest of the PDF engine.
block = block.replace('\\"', '"').replace('\\\\', '\\')
s = s[:start] + block + s[end:]
p.write_text(s)
