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
- `p`: copy the previous page, available after the first page
- `c`: copy the current page again, available after the first page
- `g`: jump to a page and copy it
- `m`: switch between image copying and extracted-text copying
- `s`: show the current state
- `h`: show help
- `q`: quit cleanly

The iterator starts at page 0, so pressing `n` first copies page 1. The `p` and `c` keys appear after the first page has been copied.
