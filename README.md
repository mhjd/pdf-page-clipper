# pdf-page-clipper

A minimal interactive tool for copying PDF pages as images or extracted text.

It is built for translation workflows where you move page by page through a PDF and paste each page into another tool.

## Requirements

- Python 3
- Poppler tools: `pdfinfo`, `pdftoppm`, `pdftotext`
- macOS clipboard tools: `pbcopy`, `osascript`

No third-party Python package is required.

## Setup

Put your PDF files in the `pdfs/` folder:

```text
pdfs/
  document.pdf
  another-document.pdf
```

## Interactive Usage

Run:

```sh
make
```

Select a PDF, then use the keys shown by the app.

Common keys:

- `n`: copy the next page
- `p`: copy the previous page, available from page 2
- `c`: copy the current page again, available from page 1
- `g`: jump to a page and copy it
- `m`: switch between image copying and extracted-text copying
- `s`: show the current state
- `h`: show help
- `q`: quit cleanly

The iterator starts at page 0, so pressing `n` first copies page 1. The `c` key appears on page 1, and `p` appears on page 2.
