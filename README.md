# pdf-page-clipper

A minimal command-line tool to copy PDF pages as clipboard-ready images or extracted text.

It is built for translation workflows where you move page by page through a PDF and paste each page into another tool.

## Requirements

- Python 3
- Poppler tools: `pdfinfo`, `pdftoppm`, `pdftotext`
- macOS clipboard tools: `pbcopy`, `osascript`

No third-party Python package is required.

## Usage

```sh
make import PDF="document.pdf"
make
make next
make previous
make current
make set PAGE=12
make image
make text
make status
```

`make import` creates one folder per PDF and refuses to overwrite an existing folder.

`make` lists imported PDF folders and PDF files in the current directory that still need to be imported.

In interactive mode, the iterator starts before page 1, so pressing `n` first copies page 1.

Press `q` or `Esc` to quit cleanly from the selection screen or the interactive page screen.
