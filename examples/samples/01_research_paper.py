"""Research paper: math environments, equation numbering, TOC, footnotes."""

from emboss import Document

doc = Document(title="Spectral Bounds for Sparse Recovery", author="J. Rivera", style="journal")
doc.table_of_contents()

doc.abstract(
    "We establish tight spectral bounds for sparse signal recovery under "
    "restricted isometry conditions, improving prior constants by a factor "
    "of two in the high-dimensional regime.",
    keywords=("compressed sensing", "RIP", "spectral bounds"),
)

doc.authors([
    {"name": "J. Rivera", "affiliation": "Dept. of Mathematics, Aldren University", "email": "jrivera@aldren.edu"},
    {"name": "K. Okafor", "affiliation": "Institute for Computational Science", "email": "okafor@ics.org"},
])

doc.heading("Introduction", level=1)
doc.paragraph(
    "Compressed sensing theory relies on the restricted isometry property "
    "(RIP) to guarantee stable recovery of sparse signals. We consider a "
    "matrix $A \\in \\mathbb{R}^{m \\times n}$ satisfying RIP of order $k$ "
    "with constant $\\delta_k$."
)

doc.heading("Main Result", level=1)
doc.paragraph("Our central inequality bounds the recovery error:")
doc.math(r"\|\hat{x} - x\|_2 \leq C_1 \frac{\|x - x_k\|_1}{\sqrt{k}} + C_2 \epsilon", display=True, number=True)

doc.paragraph(
    "where the constants satisfy the system in @eq:constants, derived from "
    "the eigenvalue decomposition below."
)
doc.math(
    r"\begin{aligned} C_1 &= \frac{2(1+\delta_{2k})}{1-\delta_{2k}} \\ "
    r"C_2 &= \frac{4\sqrt{1+\delta_{2k}}}{1-\delta_{2k}} \end{aligned}",
    display=True, number=True, tag="constants",
)

doc.paragraph("The recovery matrix admits the block decomposition:")
doc.math(r"A = \begin{pmatrix} A_{11} & A_{12} \\ A_{21} & A_{22} \end{pmatrix}", display=True)

doc.paragraph(
    "As shown in @eq:constants, tightening the isometry constant directly "
    "improves both terms simultaneously.[^1]"
)
doc.footnote("This mirrors the argument in Candes & Tao (2005) but with a sharper union bound.")

doc.heading("Experimental Validation", level=1)
doc.paragraph("Table 1 summarizes recovery error across sparsity levels.")
doc.table(
    headers=["Sparsity k", "RIP constant", "Recovery error"],
    rows=[["10", "0.14", "0.0021"], ["25", "0.31", "0.0087"], ["50", "0.58", "0.0412"]],
    caption="Recovery error as a function of sparsity level.",
)

doc.heading("Conclusion", level=1)
doc.paragraph("The improved constants close roughly half the gap to the known lower bound.")

doc.bibliography([
    {"key": "candes2005", "authors": ["E. Candes", "T. Tao"], "title": "Decoding by linear programming", "year": "2005", "journal": "IEEE Trans. Info. Theory"},
    {"key": "donoho2006", "authors": ["D. Donoho"], "title": "Compressed sensing", "year": "2006", "journal": "IEEE Trans. Info. Theory"},
])

doc.save("examples/samples/01_research_paper.pdf")
print("wrote 01_research_paper.pdf")
