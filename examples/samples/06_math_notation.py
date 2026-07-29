"""Math typesetting: LaTeX environments, MathML input, real font metrics."""

from emboss import Document

doc = Document(title="Notes on Linear Systems", style="academic")

doc.heading("Matrix Forms", level=1)
doc.paragraph("A linear system in matrix form:")
doc.math(r"A\mathbf{x} = \mathbf{b}", display=True)

doc.paragraph("Written out as an augmented matrix:")
doc.math(
    r"\begin{pmatrix} 2 & 1 & -1 \\ -3 & -1 & 2 \\ -2 & 1 & 2 \end{pmatrix}"
    r"\begin{pmatrix} x \\ y \\ z \end{pmatrix} ="
    r"\begin{pmatrix} 8 \\ -11 \\ -3 \end{pmatrix}",
    display=True,
)

doc.heading("Piecewise Definitions", level=1)
doc.math(
    r"f(x) = \begin{cases} x^2 & x \geq 0 \\ -x^2 & x < 0 \end{cases}",
    display=True,
    number=True,
    tag="piecewise",
)
doc.paragraph("As shown in @eq:piecewise, the function is smooth but not twice differentiable at zero.")

doc.heading("Aligned Derivation", level=1)
doc.math(
    r"\begin{aligned} "
    r"\nabla \cdot \mathbf{E} &= \frac{\rho}{\epsilon_0} \\ "
    r"\nabla \times \mathbf{E} &= -\frac{\partial \mathbf{B}}{\partial t} "
    r"\end{aligned}",
    display=True,
)

doc.heading("Summation and Limits", level=1)
doc.math(r"\sum_{i=1}^{n} i = \frac{n(n+1)}{2}", display=True)
doc.math(r"\lim_{x \to \infty} \left(1 + \frac{1}{x}\right)^x = e", display=True)

doc.heading("MathML Input", level=1)
doc.paragraph("The same quadratic formula, supplied as presentation MathML rather than LaTeX:")
doc.math(
    "<math><mrow><mi>x</mi><mo>=</mo>"
    "<mfrac><mrow><mo>-</mo><mi>b</mi><mo>&#177;</mo>"
    "<msqrt><mrow><msup><mi>b</mi><mn>2</mn></msup>"
    "<mo>-</mo><mn>4</mn><mi>a</mi><mi>c</mi></mrow></msqrt></mrow>"
    "<mrow><mn>2</mn><mi>a</mi></mrow></mfrac></mrow></math>",
    display=True,
)

doc.heading("Blackboard and Script Alphabets", level=1)
doc.paragraph(
    "Real math alphabets from a bundled font, not synthetic bold/italic: "
    "$\\mathbb{R}$ for the reals, $\\mathcal{L}$ for a Lagrangian, "
    "$\\mathfrak{g}$ for a Lie algebra."
)

doc.save("examples/samples/06_math_notation.pdf")
print("wrote 06_math_notation.pdf")
