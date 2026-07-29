# Sample documents

Each script renders a self-contained PDF exercising a different part of Emboss. Run any of them directly (`python examples/samples/01_research_paper.py`); output is written to `examples/output/`.

| Script | Demonstrates |
|---|---|
| `01_research_paper.py` | Visible TOC, abstract, authors, numbered equations, `@eq` references, bibliography |
| `02_executive_brief.py` | Cover page, stat tiles, pull quote, multi-series chart with headline/source line |
| `03_architecture_doc.py` | Diagram element (layered DAG layout), code blocks, landscape page section for a wide table |
| `04_investor_deck.py` | `SlideDeck` builder: title/divider/stat/chart/bullet/code/quote/closing slides |
| `05_print_production_cmyk.py` | CMYK color mode, spot color strings, PDF/A archival output |
| `06_math_notation.py` | LaTeX environments (matrix, cases, aligned), MathML input, math alphabets |
| `07_llm_markdown_input.py` | The core product loop: raw LLM Markdown (with YAML front matter) to structured PDF |
