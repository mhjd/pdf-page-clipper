# Project Purpose

`pdf-page-clipper` exists to make PDF-based translation work faster.

Some translation workflows require sending one page at a time to another tool. Doing that manually is repetitive: open the PDF, find the next page, copy text when available, or capture the page as an image when text extraction is not useful.

This project provides a small interactive terminal app for that workflow:

- put PDFs in `pdfs/`;
- choose a PDF;
- move through it page by page;
- copy each page either as an image or as extracted text;
- keep the current position for each PDF.

The app should stay simple, local, and predictable. It should avoid unnecessary dependencies, hidden services, and complex setup.
