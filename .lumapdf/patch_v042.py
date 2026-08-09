from pathlib import Path
import re

ROOT = Path("LumaPDF_RazrFold_2026_v02")
ENGINE = ROOT / "app/src/main/java/com/tstudio/lumapdf/editor/MuPdfEngine.kt"
BUILD = ROOT / "app/build.gradle.kts"

s = ENGINE.read_text()

# The direct-content v0.2.3 engine is the required base. Abort rather than silently
# falling back to FreeText annotations.
for needle in ("private fun editTextAt", "private fun appendPageText", "private fun appendContentStream"):
    if needle not in s:
        raise SystemExit(f"Required direct-content engine marker missing: {needle}")

# Track the final expected text per edited page region. A map avoids a false save failure
# when the same text box is edited several times before Save As.
state_marker = "    private lateinit var workingFile: File\n    private var document: PDFDocument? = null\n"
state_replacement = """    private lateinit var workingFile: File
    private var document: PDFDocument? = null
    private val pendingTextChecks = mutableMapOf<String, Pair<Int, String>>()
"""
if state_marker not in s:
    raise SystemExit("Engine state marker not found")
s = s.replace(state_marker, state_replacement, 1)

open_marker = "        document = opened.asPDF().also { it.enableJournal() }\n"
if open_marker not in s:
    raise SystemExit("Open-document marker not found")
s = s.replace(open_marker, open_marker + "        pendingTextChecks.clear()\n", 1)

# Text deletion must apply only the redaction created for this edit. Page-wide redaction
# can accidentally apply unrelated/stale redaction annotations.
old_text_redaction = """                    val redaction = page.createAnnotation(PDFAnnotation.TYPE_REDACT)
                    redaction.rect = padded(rect, 0.7f)
                    redaction.update()
                    page.applyRedactions(
                        false,
                        PDFPage.REDACT_IMAGE_NONE,
                        PDFPage.REDACT_LINE_ART_NONE,
                        PDFPage.REDACT_TEXT_REMOVE,
                    )
"""
new_text_redaction = """                    val redaction = page.createAnnotation(PDFAnnotation.TYPE_REDACT)
                    redaction.rect = padded(rect, 0.25f)
                    redaction.update()
                    require(redaction.applyRedaction(
                        false,
                        PDFPage.REDACT_IMAGE_NONE,
                        PDFPage.REDACT_LINE_ART_NONE,
                        PDFPage.REDACT_TEXT_REMOVE,
                    )) { "Could not remove the original text from this PDF." }
                    runCatching { page.deleteAnnotation(redaction) }
"""
if old_text_redaction not in s:
    raise SystemExit("Expected text redaction block not found")
s = s.replace(old_text_redaction, new_text_redaction, 1)

# Record the post-transaction result for persistence verification. Restrict this insertion
# to editTextAt so image/annotation operations are not affected.
edit_start = s.index("    private fun editTextAt")
append_start = s.index("    /**", edit_start)
edit_block = s[edit_start:append_start]
end_marker = "            doc.endOperation()\n"
if edit_block.count(end_marker) != 1:
    raise SystemExit("Unexpected editTextAt transaction shape")
probe_code = """            doc.endOperation()
            val key = textProbeKey(pageIndex, rect)
            val probe = persistenceProbe(text)
            if (probe.isEmpty()) pendingTextChecks.remove(key)
            else pendingTextChecks[key] = pageIndex to probe
"""
edit_block = edit_block.replace(end_marker, probe_code, 1)
s = s[:edit_start] + edit_block + s[append_start:]

# Harden image removal/replacement too: only apply each operation's own redaction.
old_image_redaction = """                page.applyRedactions(
                    false,
                    PDFPage.REDACT_IMAGE_REMOVE,
                    PDFPage.REDACT_LINE_ART_NONE,
                    PDFPage.REDACT_TEXT_NONE,
                )
"""
new_image_redaction = """                require(redaction.applyRedaction(
                    false,
                    PDFPage.REDACT_IMAGE_REMOVE,
                    PDFPage.REDACT_LINE_ART_NONE,
                    PDFPage.REDACT_TEXT_NONE,
                )) { "Could not remove the selected image from this PDF." }
                runCatching { page.deleteAnnotation(redaction) }
"""
if old_image_redaction in s:
    s = s.replace(old_image_redaction, new_image_redaction, 1)

inline_old = "page.applyRedactions(false, PDFPage.REDACT_IMAGE_REMOVE, PDFPage.REDACT_LINE_ART_NONE, PDFPage.REDACT_TEXT_NONE)"
inline_new = "require(redaction.applyRedaction(false, PDFPage.REDACT_IMAGE_REMOVE, PDFPage.REDACT_LINE_ART_NONE, PDFPage.REDACT_TEXT_NONE)) { \"Could not replace the selected image.\" }; runCatching { page.deleteAnnotation(redaction) }"
s = s.replace(inline_old, inline_new)

# Saving edited text no longer depends on annotation baking. Direct text is already a real
# page /Contents stream. Reopen the serialized PDF and verify the final expected text exists.
old_save = """        // Bake our text/image/ink annotations into real page content while preserving form widgets.
        doc.bake(true, false)
        doc.save(out.absolutePath, "garbage=4,compress,compress-images")
        resolver.openOutputStream(target, "w").use { output ->
"""
new_save = """        // Direct text is already page content. Preserve PDF annotations/forms as objects.
        doc.save(out.absolutePath, "garbage=2,compress,compress-images")
        require(out.exists() && out.length() > 32L) { "MuPDF did not produce a valid output file." }
        verifySavedText(out)
        resolver.openOutputStream(target, "w").use { output ->
"""
if old_save not in s:
    raise SystemExit("Expected Save As bake block not found")
s = s.replace(old_save, new_save, 1)

reopen_marker = "        document = Document.openDocument(workingFile.absolutePath).asPDF().also { it.enableJournal() }\n        out.delete()\n"
reopen_replacement = "        document = Document.openDocument(workingFile.absolutePath).asPDF().also { it.enableJournal() }\n        pendingTextChecks.clear()\n        out.delete()\n"
if reopen_marker not in s:
    raise SystemExit("Save reopen marker not found")
s = s.replace(reopen_marker, reopen_replacement, 1)

helpers = r'''    private fun textProbeKey(pageIndex: Int, rect: Rect): String {
        fun q(value: Float): Int = (value * 4f).toInt()
        return "$pageIndex:${q(rect.x0)}:${q(rect.y0)}:${q(rect.x1)}:${q(rect.y1)}"
    }

    private fun persistenceProbe(text: String): String = text
        .replace("\r\n", "\n")
        .replace('\r', '\n')
        .lineSequence()
        .map { sanitizePdfText(it).trim() }
        .firstOrNull { it.length >= 2 }
        ?.take(48)
        .orEmpty()

    private fun verifySavedText(file: File) {
        if (pendingTextChecks.isEmpty()) return
        val opened = Document.openDocument(file.absolutePath)
        require(opened.isPDF) { "Saved output is not a readable PDF." }
        val pdf = opened.asPDF()
        try {
            pendingTextChecks.values.distinct().forEach { (pageIndex, probe) ->
                require(pageIndex in 0 until pdf.countPages()) {
                    "Save verification failed: an edited page no longer exists."
                }
                val page = pdf.loadPage(pageIndex)
                try {
                    require(page.search(probe).isNotEmpty()) {
                        "Save verification failed: edited text did not survive PDF serialization."
                    }
                } finally {
                    page.destroy()
                }
            }
        } finally {
            pdf.destroy()
        }
    }

'''
close_marker = "    fun close() {\n"
if close_marker not in s:
    raise SystemExit("Close marker not found")
s = s.replace(close_marker, helpers + close_marker, 1)

close_body = """        document?.destroy()
        document = null
        if (::workingFile.isInitialized) runCatching { workingFile.delete() }
"""
close_replacement = """        document?.destroy()
        document = null
        pendingTextChecks.clear()
        if (::workingFile.isInitialized) runCatching { workingFile.delete() }
"""
if close_body not in s:
    raise SystemExit("Close body marker not found")
s = s.replace(close_body, close_replacement, 1)

# Safety assertions before writing the engine.
edit_start = s.index("    private fun editTextAt")
append_start = s.index("    /**", edit_start)
edit_block = s[edit_start:append_start]
if "page.applyRedactions(" in edit_block:
    raise SystemExit("Page-wide redaction remains in text edit path")
if "redaction.applyRedaction(" not in edit_block or "appendPageText(doc, page, rect, text, style)" not in edit_block:
    raise SystemExit("Direct text transaction is incomplete")
if "TYPE_FREE_TEXT" in s:
    raise SystemExit("FreeText text replacement unexpectedly present")
if "doc.bake(true, false)" in s:
    raise SystemExit("Save-time annotation bake unexpectedly present")

ENGINE.write_text(s)

# Version bump and stable development key so this installs over the persistent-key builds.
b = BUILD.read_text()
b = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 5", b, count=1)
b = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.2-direct-text"', b, count=1)
if "signingConfigs {" not in b:
    marker = """    buildFeatures {
        viewBinding = false
        buildConfig = true
    }
"""
    signing = """    signingConfigs {
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
"""
    if marker not in b:
        raise SystemExit("buildFeatures marker not found")
    b = b.replace(marker, signing, 1)
BUILD.write_text(b)
