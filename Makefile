.PHONY: open import status next previous current copy set mode image text render help

open:
	@python3 pdfclip.py open

import:
	@test -n "$(PDF)" || (echo 'Usage: make import PDF="fleurs du mal.pdf"'; exit 2)
	@python3 pdfclip.py import "$(PDF)"

status:
	@python3 pdfclip.py status

next:
	@python3 pdfclip.py next

previous:
	@python3 pdfclip.py previous

current:
	@python3 pdfclip.py current

copy:
	@test -n "$(PAGE)" || (echo 'Usage: make copy PAGE=3'; exit 2)
	@python3 pdfclip.py copy "$(PAGE)"

set:
	@test -n "$(PAGE)" || (echo 'Usage: make set PAGE=3'; exit 2)
	@python3 pdfclip.py set "$(PAGE)"

mode:
	@python3 pdfclip.py mode $(MODE)

image:
	@python3 pdfclip.py mode image

text:
	@python3 pdfclip.py mode text

render:
	@test -n "$(PDF)" || (echo 'Usage: make render PDF="fleurs du mal.pdf"'; exit 2)
	@python3 pdfclip.py render "$(PDF)"

help:
	@python3 pdfclip.py --help
