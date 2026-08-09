from pathlib import Path

path = Path('LumaPDF_RazrFold_2026_v02/app/src/main/java/com/tstudio/lumapdf/MainActivity.kt')
s = path.read_text()
replacements = {
    '    private var zoomButton: MaterialButton? = null': '    private var zoomButton: LinearLayout? = null',
    '        fun addTool(glyph: String, label: String, action: () -> Unit): MaterialButton =': '        fun addTool(glyph: String, label: String, action: () -> Unit): LinearLayout =',
    '        zoomButton?.text = "$percent%\\nView"': '        (zoomButton?.getChildAt(0) as? TextView)?.text = "$percent%"',
}
for old, new in replacements.items():
    if old not in s:
        raise SystemExit(f'Expected v0.5 compile-fix marker missing: {old}')
    s = s.replace(old, new, 1)
path.write_text(s)
