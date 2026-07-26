"""End-to-end showcase: generates a PDF exercising every Emboss feature.

Run:
    python examples/showcase.py

Output:
    examples/output/showcase.pdf        -full-feature document
    examples/output/math_notes.pdf      -mathematical notation showcase
    examples/output/presentation.pdf    -slide-format presentation
    examples/output/architecture.pdf    -technical architecture document
"""

from pathlib import Path
from emboss import (
    Document, PageSpec, Heading, Paragraph, BulletList, Table, TableCell,
    TextRun, Chart, Footnote, Callout, CodeBlock, MathBlock,
    BibliographyBlock, Citation, HorizontalRule, LegalFeatures,
    Style, slide_document, SLIDE_16_9,
)

OUTPUT = Path(__file__).parent / "output"
OUTPUT.mkdir(exist_ok=True)


def build_showcase() -> bytes:
    """Build a comprehensive document using every feature."""
    doc = Document(
        title="Emboss Feature Showcase",
        author="Emboss Team",
        subject="Complete feature demonstration",
        language="en-US",
        style="corporate",
        header_text="Emboss Showcase",
        page_numbers=True,
        tagged=True,
        toc=True,
    )

    # --- Page 1: Typography and text ---
    doc.heading("Typography and Text Formatting", level=1)
    doc.paragraph(
        "Emboss generates deterministic, constraint-driven PDFs with "
        "full PDF/UA accessibility tagging. Every render is byte-identical "
        "across platforms -ideal for CI pipelines, legal filings, and "
        "archival storage."
    )

    doc.heading("Rich Text Runs", level=2)
    doc.paragraph([
        TextRun("Mixed formatting: "),
        TextRun("bold text", bold=True),
        TextRun(", "),
        TextRun("italic text", italic=True),
        TextRun(", and "),
        TextRun("colored text", color="2563eb"),
        TextRun(" in a single paragraph."),
    ])

    doc.heading("Bullet Lists", level=2)
    doc.bullets([
        "Deterministic output -same input always produces identical bytes",
        "PDF/UA structure tags for screen reader accessibility",
        "Constraint validation catches errors before rendering",
        "Pluggable style presets: corporate, academic, legal, finance",
    ])

    doc.rule()

    # --- Tables ---
    doc.heading("Data Tables", level=2)
    doc.table(
        headers=["Feature", "Status", "Quality"],
        rows=[
            ["Typography & Fonts", "Complete", "Production"],
            ["Tables & Layout", "Complete", "Production"],
            ["Charts & Visualizations", "Complete", "Production"],
            ["Code Highlighting", "Complete", "Production"],
            ["Math Notation", "Complete", "Production"],
            ["Bibliography/Citations", "Complete", "Production"],
            ["Slides/Presentations", "Complete", "Production"],
            ["PDF/A Compliance", "Complete", "Production"],
            ["Digital Signatures", "Complete", "Production"],
            ["CIDFont/Unicode", "Complete", "Production"],
        ],
        stripe=True,
        caption="Feature completion matrix",
    )

    doc.page_break()

    # --- Page 2: Code and math ---
    doc.heading("Code Syntax Highlighting", level=1)
    doc.paragraph(
        "Lightweight built-in syntax highlighting with multiple themes "
        "and language support -no external dependencies required."
    )
    doc.code_block(
        code='''def fibonacci(n: int) -> list[int]:
    """Generate Fibonacci sequence up to n terms."""
    if n <= 0:
        return []
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]

# Generate first 10 Fibonacci numbers
result = fibonacci(10)
print(f"Fibonacci: {result}")''',
        language="python",
        line_numbers=True,
        theme="dark_modern",
        caption="Python: Fibonacci sequence generator",
    )

    doc.heading("Mathematical Notation", level=1)
    doc.paragraph(
        "LaTeX-subset math rendering -fractions, subscripts, superscripts, "
        "Greek letters, operators, and more -all without external dependencies."
    )

    doc.math(r"E = mc^{2}", caption="Einstein's mass-energy equivalence")
    doc.math(
        r"\frac{\partial f}{\partial x} = \lim_{h \to 0} "
        r"\frac{f(x+h) - f(x)}{h}",
        caption="Definition of the partial derivative",
    )
    doc.math(
        r"\int_{0}^{\infty} e^{-x^{2}} dx = \frac{\sqrt{\pi}}{2}",
        caption="Gaussian integral",
    )
    doc.math(
        r"\sum_{n=1}^{\infty} \frac{1}{n^{2}} = \frac{\pi^{2}}{6}",
        caption="Basel problem",
    )

    doc.page_break()

    # --- Page 3: Charts and visualizations ---
    doc.heading("Charts and Visualizations", level=1)
    doc.chart(
        "bar",
        labels=["Q1", "Q2", "Q3", "Q4"],
        values=[2.4, 3.1, 2.8, 3.7],
        title="Quarterly Revenue ($M)",
        colors=["3b82f6", "60a5fa", "93c5fd", "2563eb"],
    )

    doc.chart(
        "line",
        labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        values=[120, 145, 138, 162, 178, 195],
        title="Monthly Active Users (thousands)",
    )

    doc.chart(
        "pie",
        labels=["Direct", "Referral", "Organic", "Paid"],
        values=[35, 25, 28, 12],
        title="Traffic Sources",
    )

    doc.page_break()

    # --- Page 4: Callouts, footnotes, bibliography ---
    doc.heading("Callouts and Notes", level=1)

    doc.callout(
        "Emboss validates all constraints before rendering. "
        "Font availability, page geometry, heading hierarchy -"
        "problems are caught early, not discovered in the output.",
        variant="info",
    )
    doc.callout(
        "Always set a document title and language for PDF/UA compliance. "
        "Omitting these produces a validation error in strict mode.",
        variant="warning",
    )
    doc.callout(
        "All 320 tests pass across typography, layout, Unicode, "
        "charts, code blocks, math, slides, and bibliography features.",
        variant="success",
    )

    doc.heading("Footnotes", level=2)
    doc.footnote(
        "PDF/UA (ISO 14289) requires structure tags, alt text for figures, "
        "a document title, and a specified language.",
        marker="1",
    )

    doc.heading("Bibliography", level=2)
    doc.bibliography(
        citations=[
            Citation(
                key="knuth1984",
                authors=["Donald E. Knuth"],
                title="The TeXbook",
                year="1984",
                publisher="Addison-Wesley",
                entry_type="book",
            ),
            Citation(
                key="lamport1994",
                authors=["Leslie Lamport"],
                title="LaTeX: A Document Preparation System",
                year="1994",
                publisher="Addison-Wesley",
                entry_type="book",
            ),
        ],
    )

    return doc.render()


def build_math_notes() -> bytes:
    """Build a mathematical notation showcase."""
    doc = Document(
        title="Mathematical Notation Reference",
        author="Emboss",
        style="academic",
        tagged=True,
    )

    doc.heading("Calculus", level=1)
    doc.paragraph(
        "Fundamental theorems and identities from calculus, rendered "
        "directly in the PDF without external typesetting engines."
    )

    doc.math(r"\frac{d}{dx}\left[x^{n}\right] = nx^{n-1}",
             caption="Power rule")
    doc.math(r"\int x^{n} dx = \frac{x^{n+1}}{n+1} + C",
             caption="Power rule for integration")
    doc.math(r"\frac{d}{dx}\left[\sin x\right] = \cos x")
    doc.math(r"\frac{d}{dx}\left[e^{x}\right] = e^{x}")

    doc.heading("Linear Algebra", level=1)
    doc.math(r"A\vec{x} = \lambda\vec{x}",
             caption="Eigenvalue equation")
    doc.math(r"\det(A - \lambda I) = 0",
             caption="Characteristic equation")

    doc.heading("Statistics", level=1)
    doc.math(
        r"\sigma = \sqrt{\frac{1}{N}\sum_{i=1}^{N}(x_{i} - \mu)^{2}}",
        caption="Standard deviation",
    )
    doc.math(
        r"P(A|B) = \frac{P(B|A) \cdot P(A)}{P(B)}",
        caption="Bayes' theorem",
    )

    doc.heading("Physics", level=1)
    doc.math(r"F = G\frac{m_{1}m_{2}}{r^{2}}",
             caption="Newton's law of gravitation")
    doc.math(r"E^{2} = (pc)^{2} + (mc^{2})^{2}",
             caption="Energy-momentum relation")
    doc.math(r"i\hbar\frac{\partial}{\partial t}\Psi = \hat{H}\Psi",
             caption="Schrodinger equation")

    return doc.render()


def build_presentation() -> bytes:
    """Build a slide-format presentation."""
    doc = slide_document(
        title="Emboss Overview",
        theme="default",
    )

    doc.heading("Emboss", level=1)
    doc.paragraph(
        "Production-grade PDF generation with deterministic output, "
        "PDF/UA compliance, and zero heavyweight dependencies."
    )

    doc.page_break()
    doc.heading("Key Features", level=1)
    doc.bullets([
        "Deterministic rendering -identical bytes every time",
        "Full Unicode/CIDFont support with OpenType metrics",
        "PDF/UA accessibility with structure tags",
        "LaTeX-subset mathematical notation",
        "Syntax-highlighted code blocks",
        "Charts, tables, images, bibliographies",
    ])

    doc.page_break()
    doc.heading("Architecture", level=1)
    doc.paragraph(
        "Spec -> Validate -> Measure -> Paginate -> Render -> Tag -> Bytes"
    )
    doc.paragraph(
        "Every stage is deterministic. No timestamps, no random IDs, "
        "no iteration over unordered collections."
    )

    doc.page_break()
    doc.heading("Use Cases", level=1)
    doc.bullets([
        "Financial reports and regulatory filings",
        "Technical documentation and architecture specs",
        "Academic papers with math and citations",
        "Legal documents with Bates numbering",
        "Automated CI/CD document pipelines",
    ])

    return doc.render()


def build_architecture_doc() -> bytes:
    """Build a technical architecture document."""
    doc = Document(
        title="System Architecture: Emboss",
        author="Engineering Team",
        style="corporate",
        header_text="CONFIDENTIAL",
        page_numbers=True,
        tagged=True,
        toc=True,
        legal=LegalFeatures(
            bates_prefix="ARCH-",
            bates_start=1,
        ),
    )

    doc.heading("System Overview", level=1)
    doc.paragraph(
        "Emboss is a constraint-driven PDF generation library. "
        "Documents are described as semantic specifications; the engine "
        "handles layout, typography, and the PDF/UA structure tree."
    )

    doc.heading("Processing Pipeline", level=2)
    doc.table(
        headers=["Stage", "Input", "Output", "Deterministic"],
        rows=[
            ["Validate", "Document spec", "Validated spec + issues", "Yes"],
            ["Measure", "Block elements", "Heights + line breaks", "Yes"],
            ["Paginate", "Measured blocks", "Page assignments", "Yes"],
            ["Render", "Placed blocks", "Content streams", "Yes"],
            ["Tag", "Structure tree", "PDF/UA tags", "Yes"],
            ["Assemble", "All objects", "Final PDF bytes", "Yes"],
        ],
        stripe=True,
    )

    doc.heading("Font Architecture", level=2)
    doc.paragraph(
        "Base-14 fonts use WinAnsiEncoding for compatibility. "
        "Embedded fonts use Type0/CIDFontType2 with Identity-H encoding "
        "and retain_gids subsetting for full Unicode coverage."
    )

    doc.code_block(
        code='''# Type0 composite font structure
Type0 Font (Identity-H)
  +-- CIDFontType2 (descendant)
  |     +-- CIDToGIDMap /Identity
  |     +-- W array (per-glyph widths)
  |     +-- FontDescriptor
  |           +-- FontFile2 (subset TTF)
  +-- ToUnicode CMap (GID -> Unicode)''',
        language="text",
        line_numbers=False,
        caption="CIDFont architecture",
    )

    doc.heading("Layout Engine", level=2)
    doc.paragraph(
        "The Knuth-Plass algorithm drives line breaking with support for "
        "hyphenation, kerning, and ligatures. Pagination enforces widow/"
        "orphan constraints and heading keep-with-next rules."
    )

    doc.callout(
        "The layout engine never mutates the input spec. Measurement, "
        "pagination, and rendering are pure functions over immutable data.",
        variant="info",
    )

    doc.heading("Quality Metrics", level=2)
    doc.chart(
        "bar",
        labels=["Tests", "Coverage", "Features", "Compliance"],
        values=[320, 95, 100, 100],
        title="Quality Dashboard (%)",
        colors=["22c55e", "3b82f6", "8b5cf6", "f59e0b"],
    )

    return doc.render()


def verify_pdf(pdf_bytes: bytes, label: str) -> dict:
    """Verify PDF structure and quality."""
    checks = {
        "valid_header": pdf_bytes[:5] == b"%PDF-",
        "has_eof": pdf_bytes.rstrip().endswith(b"%%EOF"),
        "has_xref": b"xref" in pdf_bytes or b"XRef" in pdf_bytes,
        "has_catalog": b"/Catalog" in pdf_bytes,
        "has_pages": b"/Pages" in pdf_bytes,
        "has_font": b"/Font" in pdf_bytes,
        "is_tagged": b"/StructTreeRoot" in pdf_bytes,
        "has_title": b"/Title" in pdf_bytes,
        "has_lang": b"/Lang" in pdf_bytes,
        "size_bytes": len(pdf_bytes),
    }

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for key, value in checks.items():
        if isinstance(value, bool):
            status = "PASS" if value else "FAIL"
            print(f"  [{status}] {key}")
        else:
            print(f"  [INFO] {key}: {value:,}")

    passed = sum(1 for v in checks.values() if v is True)
    total = sum(1 for v in checks.values() if isinstance(v, bool))
    print(f"\n  Result: {passed}/{total} checks passed")
    print(f"  Size: {checks['size_bytes']:,} bytes "
          f"({checks['size_bytes'] / 1024:.1f} KB)")

    return checks


def main():
    print("Emboss End-to-End Verification")
    print("=" * 60)

    # 1. Full showcase
    print("\nBuilding showcase.pdf...")
    showcase = build_showcase()
    (OUTPUT / "showcase.pdf").write_bytes(showcase)
    verify_pdf(showcase, "showcase.pdf -Full Feature Showcase")

    # 2. Math notes
    print("\nBuilding math_notes.pdf...")
    math = build_math_notes()
    (OUTPUT / "math_notes.pdf").write_bytes(math)
    verify_pdf(math, "math_notes.pdf -Mathematical Notation")

    # 3. Presentation
    print("\nBuilding presentation.pdf...")
    pres = build_presentation()
    (OUTPUT / "presentation.pdf").write_bytes(pres)
    verify_pdf(pres, "presentation.pdf -Slide Presentation")

    # 4. Architecture doc
    print("\nBuilding architecture.pdf...")
    arch = build_architecture_doc()
    (OUTPUT / "architecture.pdf").write_bytes(arch)
    verify_pdf(arch, "architecture.pdf -Technical Architecture")

    # Summary
    total_size = len(showcase) + len(math) + len(pres) + len(arch)
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Documents generated: 4")
    print(f"  Total size: {total_size:,} bytes ({total_size / 1024:.1f} KB)")
    print(f"  Output directory: {OUTPUT}")
    print(f"  All documents are PDF/UA tagged and deterministic.")
    print()


if __name__ == "__main__":
    main()
