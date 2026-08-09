from pathlib import Path
import re

root = Path('LumaPDF_RazrFold_2026_v042')
base = root / 'app/src/main/java/com/tstudio/lumapdf'
engine = base / 'editor/MuPdfEngine.kt'
s = engine.read_text()

# v0.4.2: edited text is real PDF page content, not a FreeText annotation.
if 'private fun appendPageText' not in s or 'appendContentStream(doc, pageObject' not in s:
    raise SystemExit('Direct page-content text engine is missing')

# Apply only the redaction created for the selected text object.
text_old = '''                    page.applyRedactions(
                        false,
                        PDFPage.REDACT_IMAGE_NONE,
                        PDFPage.REDACT_LINE_ART_NONE,
                        PDFPage.REDACT_TEXT_REMOVE,
                    )'''
text_new = '''                    require(redaction.applyRedaction(
                        false,
                        PDFPage.REDACT_IMAGE_NONE,
                        PDFPage.REDACT_LINE_ART_NONE,
                        PDFPage.REDACT_TEXT_REMOVE,
                    )) { "Could not remove the original text from this PDF." }'''
if text_old not in s:
    raise SystemExit('Text redaction block is missing')
s = s.replace(text_old, text_new, 1)

# Apply image redactions locally as well, so editing one object cannot consume unrelated redactions.
image_old = '''                page.applyRedactions(
                    false,
                    PDFPage.REDACT_IMAGE_REMOVE,
                    PDFPage.REDACT_LINE_ART_NONE,
                    PDFPage.REDACT_TEXT_NONE,
                )'''
image_new = '''                require(redaction.applyRedaction(
                    false,
                    PDFPage.REDACT_IMAGE_REMOVE,
                    PDFPage.REDACT_LINE_ART_NONE,
                    PDFPage.REDACT_TEXT_NONE,
                )) { "Could not remove the selected image." }'''
if image_old in s:
    s = s.replace(image_old, image_new, 1)
s = s.replace(
    'page.applyRedactions(false, PDFPage.REDACT_IMAGE_REMOVE, PDFPage.REDACT_LINE_ART_NONE, PDFPage.REDACT_TEXT_NONE)',
    'require(redaction.applyRedaction(false, PDFPage.REDACT_IMAGE_REMOVE, PDFPage.REDACT_LINE_ART_NONE, PDFPage.REDACT_TEXT_NONE)) { "Could not replace the selected image." }'
)

# Remember successful text mutations until Save As has reopened and verified them.
doc_field = 'private var document: PDFDocument? = null'
if doc_field not in s:
    raise SystemExit('PDF document field is missing')
s = s.replace(doc_field, doc_field + '\n    private val pendingTextChecks = mutableListOf<Pair<Int, String>>()', 1)

start = s.find('    private fun editTextAt(')
end = s.find('\n    /**', start)
if start < 0 or end < 0:
    raise SystemExit('editTextAt block not found')
block = s[start:end]
needle = '            doc.endOperation()'
if needle not in block:
    raise SystemExit('editTextAt endOperation not found')
block = block.replace(
    needle,
    needle + '\n            if (text.isNotBlank()) pendingTextChecks += pageIndex to sanitizePdfText(text)',
    1,
)
s = s[:start] + block + s[end:]

# Saving text must not depend on annotation baking. The replacement is already in /Contents.
save_start = s.find('    fun saveAs(target: Uri) {')
save_end = s.find('\n    fun close() {', save_start)
if save_start < 0 or save_end < 0:
    raise SystemExit('saveAs block not found')
save_block = s[save_start:save_end]
old_save = '''        // Bake our text/image/ink annotations into real page content while preserving form widgets.
        doc.bake(true, false)
        doc.save(out.absolutePath, "garbage=4,compress,compress-images")'''
new_save = '''        // Text edits already live in the real page /Contents stream. Keep annotations/forms
        // as normal PDF objects instead of destructively baking the entire document on save.
        doc.save(out.absolutePath, "garbage=2,compress,compress-images")
        verifySavedText(out)'''
if old_save not in save_block:
    raise SystemExit('Expected bake/save block not found')
save_block = save_block.replace(old_save, new_save, 1)
# Clear verification probes only after the exported file has been copied and reopened successfully.
save_block = save_block.replace(
    '        out.delete()\n    }',
    '        pendingTextChecks.clear()\n        out.delete()\n    }',
    1,
)
s = s[:save_start] + save_block + s[save_end:]

verify_fn = '''
    private fun verifySavedText(file: File) {
        if (pendingTextChecks.isEmpty()) return
        val checkDoc = Document.openDocument(file.absolutePath).asPDF()
        try {
            pendingTextChecks.distinct().forEach { (pageIndex, rawText) ->
                val probes = rawText
                    .lineSequence()
                    .map { it.trim() }
                    .filter { it.length >= 2 }
                    .take(4)
                    .toList()
                if (probes.isEmpty()) return@forEach
                val page = checkDoc.loadPage(pageIndex)
                try {
                    probes.forEach { probe ->
                        require(page.search(probe).isNotEmpty()) {
                            "Save verification failed: edited text did not survive PDF serialization."
                        }
                    }
                } finally {
                    page.destroy()
                }
            }
        } finally {
            checkDoc.destroy()
        }
    }

'''
close_marker = '    fun close() {'
if close_marker not in s:
    raise SystemExit('close() marker not found')
s = s.replace(close_marker, verify_fn + close_marker, 1)
engine.write_text(s)

# PDF pages should always be visually composited onto white paper, independent of app dark mode.
canvas = base / 'editor/PageCanvasView.kt'
c = canvas.read_text()
if 'pageBackgroundPaint' not in c:
    c = c.replace(
        '    private val pagePaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)\n',
        '    private val pagePaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)\n'
        '    private val pageBackgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE }\n',
        1,
    )
    c = c.replace(
        '        canvas.drawRoundRect(RectF(left + 3, top + 8, left + drawW + 3, top + drawH + 8), 8f, 8f, shadowPaint)\n'
        '        canvas.drawBitmap(bm, null, dst, pagePaint)',
        '        canvas.drawRoundRect(RectF(left + 3, top + 8, left + drawW + 3, top + drawH + 8), 8f, 8f, shadowPaint)\n'
        '        canvas.drawRect(dst, pageBackgroundPaint)\n'
        '        canvas.drawBitmap(bm, null, dst, pagePaint)',
        1,
    )
c = c.replace(
    '        if (mode == Mode.SELECT) {\n            s.textObjects.forEach { canvas.drawRect(toScreen(it.rect), editHintPaint) }\n        }\n',
    '        // Text hit targets stay invisible until the user taps an object.\n',
    1,
)
canvas.write_text(c)

# Failed edits immediately redraw the rolled-back PDF instead of leaving stale pixels onscreen.
main = base / 'MainActivity.kt'
m = main.read_text()
m = m.replace(
    'result.onSuccess { renderCurrentPage() }.onFailure { toast(it.message ?: "$label failed") }',
    'result.onSuccess { renderCurrentPage() }.onFailure {\n'
    '                renderCurrentPage()\n'
    '                toast(it.message ?: "$label failed")\n'
    '            }',
    1,
)
main.write_text(m)

# Stable signature + unambiguous version number.
build = root / 'app/build.gradle.kts'
b = build.read_text()
b = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 5', b, count=1)
b = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.2-direct-text"', b, count=1)
feature = '''    buildFeatures {
        viewBinding = false
        buildConfig = true
    }
'''
signing = '''    signingConfigs {
        create("lumaDev") {
            storeFile = file("lumapdf-dev.keystore")
            storePassword = "lumapdfdev"
            keyAlias = "lumapdf-dev"
            keyPassword = "lumapdfdev"
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("lumaDev")
        }
    }

    buildFeatures {
        viewBinding = false
        buildConfig = true
    }
'''
if 'signingConfigs {' not in b:
    if feature not in b:
        raise SystemExit('buildFeatures block not found for signing config')
    b = b.replace(feature, signing, 1)
build.write_text(b)

print('v0.4.2 direct-content persistence patch applied successfully')
