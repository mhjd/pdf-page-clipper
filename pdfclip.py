#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import sys
import termios
import tty
from pathlib import Path


DEFAULT_DPI = 200
STATE_FILE = "state.yml"
GLOBAL_STATE_FILE = ".pdfclip.yml"
VALID_MODES = {"image", "text"}


class AppError(Exception):
    pass


def require_tool(name):
    if not shutil.which(name):
        raise AppError(f"missing tool: {name}")


def run(cmd, input_text=None):
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise AppError(message)


def slugify(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "pdf"


def default_images_dir(pdf_path):
    return pdf_path.with_name(f"{slugify(pdf_path.stem)}_pages")


def state_path(images_dir):
    return images_dir / STATE_FILE


def global_state_path():
    return Path.cwd() / GLOBAL_STATE_FILE


def parse_simple_yaml(path):
    data = {}
    if not path.exists():
        return data

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        elif value.isdigit():
            value = int(value)
        data[key.strip()] = value
    return data


def yaml_quote(value):
    value = str(value)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_state(images_dir, state):
    images_dir.mkdir(parents=True, exist_ok=True)
    ordered_keys = ["pdf", "images_dir", "current_page", "page_count", "mode", "dpi"]
    lines = []
    for key in ordered_keys:
        if key not in state:
            continue
        value = state[key]
        if isinstance(value, int):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {yaml_quote(value)}")
    state_path(images_dir).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_global_state(images_dir):
    data = {"last_images_dir": str(Path(images_dir).resolve())}
    lines = [f"last_images_dir: {yaml_quote(data['last_images_dir'])}"]
    global_state_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def page_count(pdf_path):
    require_tool("pdfinfo")
    output = run(["pdfinfo", str(pdf_path)])
    for line in output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise AppError("could not read the PDF page count")


def load_state(pdf_path, images_dir=None, dpi=DEFAULT_DPI):
    pdf_path = pdf_path.resolve()
    images_dir = (images_dir or default_images_dir(pdf_path)).resolve()
    existing = parse_simple_yaml(state_path(images_dir))
    count = existing.get("page_count") or page_count(pdf_path)
    mode = existing.get("mode", "image")
    if mode not in VALID_MODES:
        mode = "image"
    current_page = int(existing.get("current_page", 0))
    current_page = clamp_state_page(current_page, count)

    state = {
        "pdf": str(pdf_path),
        "images_dir": str(images_dir),
        "current_page": current_page,
        "page_count": int(count),
        "mode": mode,
        "dpi": int(existing.get("dpi", dpi)),
    }
    write_state(images_dir, state)
    return state


def load_state_from_dir(images_dir, dpi=DEFAULT_DPI):
    images_dir = images_dir.resolve()
    existing = parse_simple_yaml(state_path(images_dir))
    if not existing:
        raise AppError(f"invalid pdfclip folder: {images_dir}")

    pdf_path = Path(str(existing.get("pdf", ""))).expanduser()
    if not pdf_path.exists():
        raise AppError(f"PDF not found for this folder: {pdf_path}")

    return load_state(pdf_path, images_dir, dpi)


def load_last_state(dpi=DEFAULT_DPI):
    existing = parse_simple_yaml(global_state_path())
    images_dir = existing.get("last_images_dir")
    if not images_dir:
        projects = discover_projects(Path.cwd())
        if len(projects) == 1:
            write_global_state(projects[0]["images_dir"])
            return projects[0]
        raise AppError('no active folder; run "make" to choose one or "make import PDF=..."')
    return load_state_from_dir(Path(str(images_dir)), dpi)


def load_target_state(target=None, dpi=DEFAULT_DPI):
    if target is None:
        return load_last_state(dpi)

    target = Path(target)
    if target.suffix.lower() == ".pdf":
        return load_state(target, None, dpi)
    return load_state_from_dir(target, dpi)


def clamp_page(page, count):
    return max(1, min(int(page), int(count)))


def clamp_state_page(page, count):
    return max(0, min(int(page), int(count)))


def page_image_path(images_dir, page):
    return images_dir / f"page-{page}.png"


def rendered_page_count(images_dir):
    return len(list(images_dir.glob("page-*.png")))


def render_images(pdf_path, images_dir, dpi=DEFAULT_DPI, force=False):
    require_tool("pdftoppm")
    count = page_count(pdf_path)
    images_dir.mkdir(parents=True, exist_ok=True)

    if force:
        for existing in images_dir.glob("page-*.png"):
            existing.unlink()

    missing = [page for page in range(1, count + 1) if not page_image_path(images_dir, page).exists()]
    if not missing:
        return count, 0

    prefix = images_dir / "page"
    run(["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)])

    for generated in images_dir.glob("page-*.png"):
        match = re.fullmatch(r"page-(\d+)\.png", generated.name)
        if not match:
            continue
        normalized = page_image_path(images_dir, int(match.group(1)))
        if generated != normalized:
            generated.replace(normalized)

    return count, len(missing)


def import_pdf(pdf_path, images_dir=None, dpi=DEFAULT_DPI):
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        raise AppError(f"PDF not found: {pdf_path}")

    images_dir = (images_dir or default_images_dir(pdf_path)).resolve()
    if images_dir.exists():
        raise AppError(
            f"folder already exists: {images_dir}\n"
            "Import stopped to avoid overwriting existing work."
        )

    count, rendered = render_images(pdf_path, images_dir, dpi, force=False)
    state = {
        "pdf": str(pdf_path),
        "images_dir": str(images_dir),
        "current_page": 0,
        "page_count": int(count),
        "mode": "image",
        "dpi": int(dpi),
    }
    write_state(images_dir, state)
    write_global_state(images_dir)
    return state, rendered


def ensure_image_ready(state):
    pdf_path = Path(state["pdf"])
    images_dir = Path(state["images_dir"])
    page = int(state["current_page"])
    if page_image_path(images_dir, page).exists():
        return
    render_images(pdf_path, images_dir, int(state["dpi"]), force=False)
    if not page_image_path(images_dir, page).exists():
        raise AppError(f"missing image for page {page}")


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


def copy_page_text(state):
    require_tool("pdftotext")
    pdf_path = Path(state["pdf"])
    page = int(state["current_page"])
    output = run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf_path), "-"])
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


def copy_current(state):
    page = int(state["current_page"])
    if page < 1:
        return None

    mode = state["mode"]
    if mode == "text":
        chars = copy_page_text(state)
        return f"copied page {page} as text ({chars} characters)"

    ensure_image_ready(state)
    image_path = page_image_path(Path(state["images_dir"]), page)
    copy_image_to_clipboard(image_path)
    return f"copied page {page} as image ({image_path.name})"


def move_and_copy(state, delta):
    current = int(state["current_page"])
    if current < 1 and delta <= 0:
        return None
    state["current_page"] = clamp_page(current + delta, int(state["page_count"]))
    write_state(Path(state["images_dir"]), state)
    return copy_current(state)


def set_page(state, page):
    state["current_page"] = clamp_page(page, int(state["page_count"]))
    write_state(Path(state["images_dir"]), state)
    return copy_current(state)


def set_mode(state, mode=None):
    if mode is None:
        mode = "text" if state["mode"] == "image" else "image"
    if mode not in VALID_MODES:
        raise AppError("invalid mode: expected 'image' or 'text'")
    state["mode"] = mode
    write_state(Path(state["images_dir"]), state)
    return f"active mode: {mode}"


def print_status(state):
    images_dir = Path(state["images_dir"])
    print(f"PDF: {state['pdf']}")
    print(f"Folder: {images_dir}")
    if int(state["current_page"]) < 1:
        print("Current page: none")
        print(f"Next page: 1 / {state['page_count']}")
    else:
        print(f"Page: {state['current_page']} / {state['page_count']}")
    print(f"Mode: {state['mode']}")
    print(f"Rendered images: {rendered_page_count(images_dir)} / {state['page_count']}")


def discover_projects(root):
    projects = []
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and state_path(candidate).exists():
            try:
                state = load_state_from_dir(candidate)
            except AppError:
                continue
            projects.append(state)
    return projects


def discover_unimported_pdfs(root):
    pdfs = []
    for candidate in sorted(root.glob("*.pdf")):
        if default_images_dir(candidate).exists():
            continue
        pdfs.append(candidate)
    return pdfs


def project_label(state):
    folder_name = Path(state["images_dir"]).name
    return f"{folder_name}"


def page_label(state):
    current = int(state["current_page"])
    if current < 1:
        return f"before page 1/{state['page_count']}"
    return f"page {current}/{state['page_count']}"


def pdf_label(pdf_path):
    return pdf_path.name


def print_selector(projects, pdfs):
    print("pdf-page-clipper")
    print()

    print("Imported PDFs")
    if projects:
        for index, state in enumerate(projects, start=1):
            print(f"  {index}. {project_label(state)}")
            print(f"     PDF: {Path(state['pdf']).name}")
            print(f"     Position: {page_label(state)}")
            print(f"     Mode: {state['mode']}")
    else:
        print("  none")

    print()
    print("PDFs to import")
    offset = len(projects)
    if pdfs:
        for index, pdf_path in enumerate(pdfs, start=offset + 1):
            print(f"  {index}. {pdf_label(pdf_path)}")
            print(f"     Folder: {default_images_dir(pdf_path).name}")
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
    if int(state["current_page"]) >= 1:
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
  r  render: create any missing page images in the PDF folder
  s  status: show the current state
  h  help: show this help
  q  quit: exit cleanly
"""
    )


def print_action(message):
    if message:
        print(message)


def interactive_state(state):
    write_global_state(state["images_dir"])
    print("pdfclip")
    print_status(state)
    print(help_text(state))

    while True:
        print(f"[{state['mode']}] {page_label(state)} > ", end="", flush=True)
        key = read_key()
        print(key_name(key))

        try:
            if key in {"q", "\x1b"}:
                print("done")
                return
            if key == "h":
                print(help_text(state))
            elif key == "n":
                print_action(move_and_copy(state, 1))
            elif key == "p":
                print_action(move_and_copy(state, -1))
            elif key == "c":
                print_action(copy_current(state))
            elif key == "g":
                raw_value = prompt_with_default("Page", state["current_page"])
                print_action(set_page(state, int(raw_value)))
            elif key == "m":
                print_action(set_mode(state))
            elif key == "r":
                total, rendered = render_images(
                    Path(state["pdf"]),
                    Path(state["images_dir"]),
                    int(state["dpi"]),
                    force=False,
                )
                state["page_count"] = total
                write_state(Path(state["images_dir"]), state)
                print(f"images ready: {total - rendered} existing, {rendered} rendered")
            elif key == "s":
                print_status(state)
            elif key in {"\n", "\r", " "}:
                continue
            else:
                print("unknown key, press h for help")
        except ValueError:
            print("invalid page number")
        except AppError as exc:
            print(f"error: {exc}")


def interactive(pdf_path, images_dir=None, dpi=DEFAULT_DPI):
    state = load_state(pdf_path, images_dir, dpi)
    interactive_state(state)


def choose_project(dpi=DEFAULT_DPI):
    projects = discover_projects(Path.cwd())
    pdfs = discover_unimported_pdfs(Path.cwd())
    choices = [("project", project) for project in projects]
    choices.extend(("pdf", pdf_path) for pdf_path in pdfs)

    if not choices:
        print("No pdfclip folder or PDF to import found.")
        return

    print_selector(projects, pdfs)

    default = 1
    raw_choice = read_choice(default, len(choices))
    if raw_choice is None:
        print("done")
        return

    try:
        choice = int(raw_choice)
    except ValueError:
        raise AppError("invalid choice")

    if choice < 1 or choice > len(choices):
        raise AppError("choice out of range")

    kind, value = choices[choice - 1]
    if kind == "pdf":
        state, rendered = import_pdf(value, None, dpi)
        print(f"created folder: {state['images_dir']}")
        print(f"rendered images: {rendered} / {state['page_count']}")
    else:
        state = value

    interactive_state(state)


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

    raw_choice = prompt_with_default("Choice", default)
    if raw_choice in {"q", "\x1b"}:
        return None
    return raw_choice


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pdfclip.py",
        description="Copy PDF pages quickly as images or text.",
    )
    parser.add_argument("--dir", dest="images_dir", type=Path, help="image and state folder")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"image resolution (default: {DEFAULT_DPI})")

    subparsers = parser.add_subparsers(dest="command")

    open_cmd = subparsers.add_parser("open", help="open a folder or PDF in interactive mode")
    open_cmd.add_argument("target", nargs="?", type=Path)

    render_cmd = subparsers.add_parser("render", help="render PDF images")
    render_cmd.add_argument("pdf", type=Path)
    render_cmd.add_argument("--force", action="store_true", help="render existing images again")

    import_cmd = subparsers.add_parser("import", help="create the dedicated folder for a PDF")
    import_cmd.add_argument("pdf", type=Path)

    for name in ["next", "previous", "current", "status"]:
        cmd = subparsers.add_parser(name)
        cmd.add_argument("target", nargs="?", type=Path)

    copy_cmd = subparsers.add_parser("copy", help="copy a specific page")
    copy_cmd.add_argument("page", type=int)
    copy_cmd.add_argument("target", nargs="?", type=Path)

    set_cmd = subparsers.add_parser("set", help="set the current page and copy it")
    set_cmd.add_argument("page", type=int)
    set_cmd.add_argument("target", nargs="?", type=Path)

    mode_cmd = subparsers.add_parser("mode", help="change or show the mode")
    mode_cmd.add_argument("mode", nargs="?", choices=sorted(VALID_MODES))
    mode_cmd.add_argument("target", nargs="?", type=Path)

    return parser


def dispatch(args):
    if args.command == "open":
        if args.target is None:
            choose_project(args.dpi)
        else:
            interactive_state(load_target_state(args.target, args.dpi))
        return

    if args.command == "import":
        state, rendered = import_pdf(args.pdf, args.images_dir, args.dpi)
        print(f"created folder: {state['images_dir']}")
        print(f"rendered images: {rendered} / {state['page_count']}")
        return

    if args.command == "render":
        state = load_state(args.pdf, args.images_dir, args.dpi)
        total, rendered = render_images(args.pdf.resolve(), Path(state["images_dir"]), args.dpi, args.force)
        state["page_count"] = total
        state["dpi"] = args.dpi
        write_state(Path(state["images_dir"]), state)
        write_global_state(state["images_dir"])
        print(f"ready folder: {state['images_dir']}")
        print(f"images: {total - rendered} existing, {rendered} rendered")
        return

    if args.command is None:
        choose_project(args.dpi)
        return

    state = load_target_state(getattr(args, "target", None), args.dpi)
    write_global_state(state["images_dir"])

    if args.command == "next":
        print_action(move_and_copy(state, 1))
    elif args.command == "previous":
        print_action(move_and_copy(state, -1))
    elif args.command == "current":
        print_action(copy_current(state))
    elif args.command == "copy":
        print_action(set_page(state, args.page))
    elif args.command == "set":
        print_action(set_page(state, args.page))
    elif args.command == "mode":
        print_action(set_mode(state, args.mode))
    elif args.command == "status":
        print_status(state)
    else:
        choose_project(args.dpi)


def normalize_argv(argv):
    if len(argv) >= 2 and Path(argv[1]).suffix.lower() == ".pdf":
        return [argv[0], "import", *argv[1:]]
    return argv


def main(argv=None):
    argv = normalize_argv(argv or sys.argv)
    parser = build_parser()
    args = parser.parse_args(argv[1:])

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
