#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
import tempfile
import termios
import tty
from pathlib import Path


DEFAULT_DPI = 200
PDF_DIR = "pdfs"
STATE_FILE = "state.yml"
VALID_MODES = {"image", "text"}
RULE = "-" * 48


class AppError(Exception):
    pass


def require_tool(name):
    if not shutil.which(name):
        raise AppError(f"missing tool: {name}")


def run(cmd):
    try:
        result = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise AppError(message)


def pdf_dir():
    path = Path.cwd() / PDF_DIR
    path.mkdir(exist_ok=True)
    return path


def state_path():
    return pdf_dir() / STATE_FILE


def yaml_quote(value):
    value = str(value)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_unquote(value):
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def page_count(pdf_path):
    require_tool("pdfinfo")
    output = run(["pdfinfo", str(pdf_path)])
    for line in output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise AppError("could not read the PDF page count")


def clamp_page(page, count):
    return max(1, min(int(page), int(count)))


def clamp_state_page(page, count):
    return max(0, min(int(page), int(count)))


def read_state_file():
    path = state_path()
    if not path.exists():
        return {}

    documents = {}
    current_name = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        if raw_line == "documents:":
            continue
        if raw_line.startswith("  ") and not raw_line.startswith("    "):
            key = raw_line.strip()
            if not key.endswith(":"):
                continue
            current_name = yaml_unquote(key[:-1])
            documents[current_name] = {}
            continue
        if raw_line.startswith("    ") and current_name and ":" in raw_line:
            key, value = raw_line.strip().split(":", 1)
            value = value.strip()
            if value.isdigit():
                documents[current_name][key] = int(value)
            else:
                documents[current_name][key] = yaml_unquote(value)
    return documents


def write_state_file(documents):
    path = state_path()
    lines = ["documents:"]
    for name in sorted(documents):
        state = documents[name]
        lines.append(f"  {yaml_quote(name)}:")
        lines.append(f"    current_page: {int(state['current_page'])}")
        lines.append(f"    page_count: {int(state['page_count'])}")
        lines.append(f"    mode: {yaml_quote(state['mode'])}")
        lines.append(f"    dpi: {int(state['dpi'])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover_pdfs():
    return sorted(pdf_dir().glob("*.pdf"))


def sync_documents(dpi=DEFAULT_DPI):
    existing = read_state_file()
    documents = {}

    for pdf_path in discover_pdfs():
        name = pdf_path.name
        previous = existing.get(name, {})
        count = int(previous.get("page_count") or page_count(pdf_path))
        mode = previous.get("mode", "image")
        if mode not in VALID_MODES:
            mode = "image"

        documents[name] = {
            "current_page": clamp_state_page(previous.get("current_page", 0), count),
            "page_count": count,
            "mode": mode,
            "dpi": int(previous.get("dpi", dpi)),
        }

    write_state_file(documents)
    return documents


def pdf_path_for(name):
    return pdf_dir() / name


def load_document(name=None):
    documents = sync_documents()
    if not documents:
        raise AppError('no PDF found; put PDF files in the "pdfs/" folder')

    if name is None:
        if len(documents) == 1:
            name = next(iter(documents))
        else:
            raise AppError('no active PDF; run "make" to choose one')

    if name not in documents:
        raise AppError(f"unknown PDF: {name}")

    return name, documents[name], documents


def save_document(name, state, documents):
    documents[name] = state
    write_state_file(documents)


def copy_text_to_clipboard(text):
    require_tool("pbcopy")
    try:
        subprocess.run(
            ["pbcopy"],
            input=text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or "pbcopy could not access the clipboard"
        raise AppError(message)


def copy_page_text(name, state):
    require_tool("pdftotext")
    page = int(state["current_page"])
    output = run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf_path_for(name)), "-"])
    text = output.strip()
    copy_text_to_clipboard(text)
    return len(text)


def copy_image_to_clipboard(path):
    require_tool("osascript")
    script = f'''
set imageFile to POSIX file "{str(path).replace('"', '\\"')}"
set the clipboard to (read imageFile as TIFF picture)
'''
    run(["osascript", "-e", script])


def render_page_to_temp_image(name, state, temp_dir):
    require_tool("pdftoppm")
    page = int(state["current_page"])
    prefix = Path(temp_dir) / "page"
    run(
        [
            "pdftoppm",
            "-png",
            "-singlefile",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            str(int(state["dpi"])),
            str(pdf_path_for(name)),
            str(prefix),
        ]
    )
    image_path = prefix.with_suffix(".png")
    if not image_path.exists():
        raise AppError(f"could not render page {page}")
    return image_path


def copy_page_image(name, state):
    with tempfile.TemporaryDirectory(prefix="pdfclip-") as temp_dir:
        image_path = render_page_to_temp_image(name, state, temp_dir)
        copy_image_to_clipboard(image_path)


def copy_current(name, state):
    page = int(state["current_page"])
    if page < 1:
        return None

    if state["mode"] == "text":
        chars = copy_page_text(name, state)
        return f"copied page {page} from {name} as text ({chars} characters)"

    copy_page_image(name, state)
    return f"copied page {page} from {name} as image"


def move_and_copy(name, state, documents, delta):
    current = int(state["current_page"])
    if current < 1 and delta <= 0:
        return None
    state["current_page"] = clamp_page(current + delta, int(state["page_count"]))
    save_document(name, state, documents)
    return copy_current(name, state)


def set_page(name, state, documents, page):
    state["current_page"] = clamp_page(page, int(state["page_count"]))
    save_document(name, state, documents)
    return copy_current(name, state)


def set_mode(name, state, documents, mode=None):
    if mode is None:
        mode = "text" if state["mode"] == "image" else "image"
    if mode not in VALID_MODES:
        raise AppError("invalid mode: expected 'image' or 'text'")
    state["mode"] = mode
    save_document(name, state, documents)
    return f"active mode for {name}: {mode}"


def page_label(state):
    current = int(state["current_page"])
    if current < 1:
        return f"page 0/{state['page_count']}"
    return f"page {current}/{state['page_count']}"


def has_current_page(state):
    return int(state["current_page"]) >= 1


def print_status(name, state):
    print(f"PDF: {name}")
    print(f"Folder: {PDF_DIR}/")
    if not has_current_page(state):
        print(f"Page: 0 / {state['page_count']}")
        print(f"Next page: 1 / {state['page_count']}")
    else:
        print(f"Page: {state['current_page']} / {state['page_count']}")
    print(f"Mode: {state['mode']}")


def print_selector(documents):
    print("pdf-page-clipper")
    print(RULE)
    print()
    print("PDFs")
    if documents:
        for index, name in enumerate(sorted(documents), start=1):
            state = documents[name]
            print(f"  {index}. {name}")
            print(f"     Position: {page_label(state)}")
            print(f"     Mode: {state['mode']}")
    else:
        print("  none")
    print()
    print("Actions")
    print("  q  quit")
    print()


def read_key():
    if not sys.stdin.isatty():
        return sys.stdin.read(1)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def key_name(key):
    if key == "\x1b":
        return "Esc"
    if key in {"\n", "\r"}:
        return ""
    return key


def prompt_with_default(prompt, default):
    try:
        import readline
    except ImportError:
        return input(f"{prompt} [{default}] ") or str(default)

    def prefill():
        readline.insert_text(str(default))
        readline.redisplay()

    readline.set_pre_input_hook(prefill)
    try:
        return input(f"{prompt}: ") or str(default)
    finally:
        readline.set_pre_input_hook()


def help_text(state):
    navigation = ["  n  next: copy the next page"]
    if has_current_page(state):
        navigation.extend(
            [
                "  p  previous: copy the previous page",
                "  c  current: copy the current page again",
            ]
        )

    return (
        """
Keys:
"""
        + "\n".join(navigation)
        + """
  g  set page: change the current page
  m  switch mode: toggle what gets copied, image or extracted text
  s  status: show the current state
  h  help: show this help
  q  quit: exit cleanly
"""
    )


def print_action(message):
    if message:
        print(message)


def interactive_document(name, state, documents):
    print()
    print(RULE)
    print("pdf-page-clipper")
    print(RULE)
    print_status(name, state)
    print(help_text(state))

    while True:
        print(f"[{state['mode']}] {name} | {page_label(state)} > ", end="", flush=True)
        key = read_key()
        print(key_name(key))

        try:
            had_current_page = has_current_page(state)
            if key in {"q", "\x1b"}:
                print("done")
                return
            if key == "h":
                print(help_text(state))
            elif key == "n":
                print_action(move_and_copy(name, state, documents, 1))
            elif key == "p":
                print_action(move_and_copy(name, state, documents, -1))
            elif key == "c":
                print_action(copy_current(name, state))
            elif key == "g":
                raw_value = prompt_with_default("Page", state["current_page"])
                print_action(set_page(name, state, documents, int(raw_value)))
            elif key == "m":
                print_action(set_mode(name, state, documents))
            elif key == "s":
                print_status(name, state)
            elif key in {"\n", "\r", " "}:
                continue
            else:
                print("unknown key, press h for help")

            if not had_current_page and has_current_page(state):
                print(help_text(state))
        except ValueError:
            print("invalid page number")
        except AppError as exc:
            print(f"error: {exc}")


def read_choice(default, count):
    if count <= 9:
        print(f"Choice [{default}] > ", end="", flush=True)
        key = read_key()
        print(key_name(key))
        if key in {"q", "\x1b"}:
            return None
        if key in {"\n", "\r"}:
            return str(default)
        return key

    raw_choice = input(f"Choice [{default}] > ").strip() or str(default)
    if raw_choice in {"q", "\x1b"}:
        return None
    return raw_choice


def choose_document(dpi=DEFAULT_DPI):
    documents = sync_documents(dpi)
    if not documents:
        print('No PDF found. Put PDF files in the "pdfs/" folder.')
        return

    names = sorted(documents)
    print_selector(documents)
    raw_choice = read_choice(1, len(names))
    if raw_choice is None:
        print("done")
        return

    try:
        choice = int(raw_choice)
    except ValueError:
        raise AppError("invalid choice")
    if choice < 1 or choice > len(names):
        raise AppError("choice out of range")

    name = names[choice - 1]
    interactive_document(name, documents[name], documents)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pdfclip.py",
        description="Copy PDF pages quickly as images or text.",
    )
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"image resolution (default: {DEFAULT_DPI})")
    return parser


def dispatch(args):
    choose_document(args.dpi)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args((argv or sys.argv)[1:])

    try:
        dispatch(args)
        return 0
    except AppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
