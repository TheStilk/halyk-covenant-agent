# Robust Table and Document Extraction for Financial PDFs

This document outlines research findings on handling issues with PDF extraction—specifically bad encodings, mojibake, and dirty scans—using `pdfplumber`, `PyMuPDF`, and modern OCR tools like `Marker` and `Surya`.

## 1. Dealing with Mojibake in `pdfplumber`
- **Root Cause:** Mojibake (garbled text) is usually a structural issue where the PDF's internal `ToUnicode` map is broken or missing. It is rarely a standard string decoding issue (e.g., `bytes.decode()`) that can be fixed with tools like `ftfy`.
- **Strategy:** `pdfplumber` relies on the internal mappings and does not have an automatic OCR fallback. A hybrid pipeline is required:
  - **Probe:** Check if `page.extract_text()` returns empty strings, very low character counts, or many replacement characters (e.g., ``).
  - **Fallback:** If the page fails the quality check, convert the page to an image (`pdf2image`) and process it with an OCR engine like `pytesseract` or `EasyOCR`.
- **Best Practices:** Use `use_text_flow=True` to improve layout interpretation. Do not apply OCR blindly to all pages due to performance costs and potential for introduced errors.

## 2. Handling Bad Encodings with `PyMuPDF`
- **Root Cause:** Similar to `pdfplumber`, missing characters or garbled symbols (like `cid:123`) often occur due to non-standard custom font encodings. 
- **Strategy:**
  - **Native Bypass:** Try adjusting extraction flags, e.g., `page.get_text(flags=0)` to bypass problematic default font mappings.
  - **Built-in OCR:** Use `page.get_textpage_ocr()` as a robust fallback. PyMuPDF can perform OCR specifically on parts of the page that lack legible digital text, preserving high-quality native text where possible.
  - **Reading Order:** Use `page.get_text("text", sort=True)` to ensure top-left to bottom-right order.
- **Best Practices:** Avoid manual encoding/decoding. If native extraction fails, preprocess page images (e.g., 300 DPI, correct orientation) before applying OCR.

## 3. Modern OCR Solutions: Marker & Surya
For complex financial documents with irregular tables, traditional tools might struggle. **Datalab's Marker and Surya** offer state-of-the-art open-source alternatives.
- **Surya:** The foundational OCR and layout analysis engine (a 650M-parameter VLM). It handles multilingual OCR, layout analysis, and reading order/table detection. It outputs raw JSON with bounding boxes.
- **Marker:** A higher-level pipeline built on top of Surya that converts PDFs to structured formats (Markdown, JSON, HTML). It is highly effective for Retrieval-Augmented Generation (RAG) pipelines and exposes a user-friendly `TableConverter` API for high-fidelity table extraction.
- **Financial Table Extraction:** Marker is highly recommended for financial tables (e.g., bank statements, 10-K reports). It runs locally (GPU, CPU, or Apple Silicon), ensuring data privacy. For extremely irregular tables, pairing these tools with an LLM for cell-level accuracy is a common pattern.

## Conclusion & Recommendation
For a project currently using `pdfplumber` and `PyMuPDF`:
1. **Short-Term:** Implement a hybrid probing strategy. Attempt native extraction (with `flags=0` in PyMuPDF) and fall back to PyMuPDF's built-in OCR (`get_textpage_ocr()`) or a Tesseract integration for pages that return mojibake or empty strings.
2. **Long-Term/Complex Tables:** Migrate the extraction pipeline to **Marker** (backed by Surya). It is specifically designed to handle complex layouts and table extractions in financial documents, outputting clean, structured Markdown that is highly compatible with downstream LLM processing.

### Sources
- [PyMuPDF OCR Documentation & Strategies](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [Marker GitHub Repository](https://github.com/VikParuchuri/marker)
- [Surya GitHub Repository](https://github.com/VikParuchuri/surya)
- Community best practices on handling mojibake and PDF encodings (Vertex AI Search Summaries)
