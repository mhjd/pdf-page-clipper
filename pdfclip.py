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
        raise AppError(f"outil introuvable: {name}")


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
    raise AppError("impossible de lire le nombre de pages du PDF")


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
        raise AppError(f"dossier pdfclip invalide: {images_dir}")

    pdf_path = Path(str(existing.get("pdf", ""))).expanduser()
    if not pdf_path.exists():
        raise AppError(f"PDF introuvable pour ce dossier: {pdf_path}")

    return load_state(pdf_path, images_dir, dpi)


def load_last_state(dpi=DEFAULT_DPI):
    existing = parse_simple_yaml(global_state_path())
    images_dir = existing.get("last_images_dir")
    if not images_dir:
        projects = discover_projects(Path.cwd())
        if len(projects) == 1:
            write_global_state(projects[0]["images_dir"])
            return projects[0]
        raise AppError("aucun dossier actif; lance 'make' pour en choisir un ou 'make import PDF=\"...\"'")
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
        raise AppError(f"PDF introuvable: {pdf_path}")

    images_dir = (images_dir or default_images_dir(pdf_path)).resolve()
    if images_dir.exists():
        raise AppError(
            f"le dossier existe déjà: {images_dir}\n"
            "Import annulé pour éviter d'écraser un travail existant."
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
        raise AppError(f"image manquante pour la page {page}")


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
        message = exc.stderr.strip() or "pbcopy a refusé l'accès au presse-papier"
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
        raise AppError("aucune page courante; appuie sur n pour copier la page 1")

    mode = state["mode"]
    if mode == "text":
        chars = copy_page_text(state)
        return f"page {page} copiée en texte ({chars} caractères)"

    ensure_image_ready(state)
    image_path = page_image_path(Path(state["images_dir"]), page)
    copy_image_to_clipboard(image_path)
    return f"page {page} copiée en image ({image_path.name})"


def move_and_copy(state, delta):
    current = int(state["current_page"])
    if current < 1 and delta <= 0:
        raise AppError("aucune page précédente; appuie sur n pour copier la page 1")
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
        raise AppError("mode invalide: attendu 'image' ou 'text'")
    state["mode"] = mode
    write_state(Path(state["images_dir"]), state)
    return f"mode actif: {mode}"


def print_status(state):
    images_dir = Path(state["images_dir"])
    print(f"PDF: {state['pdf']}")
    print(f"Dossier: {images_dir}")
    if int(state["current_page"]) < 1:
        print(f"Page courante: aucune")
        print(f"Prochaine page: 1 / {state['page_count']}")
    else:
        print(f"Page: {state['current_page']} / {state['page_count']}")
    print(f"Mode: {state['mode']}")
    print(f"Images générées: {rendered_page_count(images_dir)} / {state['page_count']}")


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


def project_label(state):
    pdf_name = Path(state["pdf"]).name
    folder_name = Path(state["images_dir"]).name
    return (
        f"{folder_name}  "
        f"{page_label(state)}  "
        f"mode {state['mode']}  "
        f"({pdf_name})"
    )


def page_label(state):
    current = int(state["current_page"])
    if current < 1:
        return f"avant page 1/{state['page_count']}"
    return f"page {current}/{state['page_count']}"


def read_key():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


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


def help_text():
    return """
Touches:
  n  next: copie la page suivante
  p  previous: copie la page précédente
  c  current: recopie la page courante
  g  set page: modifier le numéro courant
  m  switch mode: alterne image / text
  r  render: génère les images manquantes
  s  status: affiche l'état
  h  help: affiche cette aide
  q  quit
"""


def interactive_state(state):
    write_global_state(state["images_dir"])
    print("pdfclip")
    print_status(state)
    print(help_text())

    while True:
        print(f"[{state['mode']}] {page_label(state)} > ", end="", flush=True)
        key = read_key()
        print(key)

        try:
            if key == "q":
                print("fin")
                return
            if key == "h":
                print(help_text())
            elif key == "n":
                print(move_and_copy(state, 1))
            elif key == "p":
                print(move_and_copy(state, -1))
            elif key == "c":
                print(copy_current(state))
            elif key == "g":
                raw_value = prompt_with_default("Page", state["current_page"])
                print(set_page(state, int(raw_value)))
            elif key == "m":
                print(set_mode(state))
            elif key == "r":
                total, rendered = render_images(
                    Path(state["pdf"]),
                    Path(state["images_dir"]),
                    int(state["dpi"]),
                    force=False,
                )
                state["page_count"] = total
                write_state(Path(state["images_dir"]), state)
                print(f"images prêtes: {total - rendered} existantes, {rendered} générées")
            elif key == "s":
                print_status(state)
            elif key in {"\n", "\r", " "}:
                continue
            else:
                print("touche inconnue, h pour l'aide")
        except ValueError:
            print("numéro de page invalide")
        except AppError as exc:
            print(f"erreur: {exc}")


def interactive(pdf_path, images_dir=None, dpi=DEFAULT_DPI):
    state = load_state(pdf_path, images_dir, dpi)
    interactive_state(state)


def choose_project(dpi=DEFAULT_DPI):
    projects = discover_projects(Path.cwd())
    if not projects:
        print("Aucun dossier pdfclip trouvé.")
        print('Pour en créer un: make import PDF="fleurs du mal.pdf"')
        return

    print("Dossiers disponibles:")
    for index, state in enumerate(projects, start=1):
        print(f"  {index}. {project_label(state)}")

    default = 1
    raw_choice = prompt_with_default("Dossier", default)
    try:
        choice = int(raw_choice)
    except ValueError:
        raise AppError("choix invalide")

    if choice < 1 or choice > len(projects):
        raise AppError("choix hors liste")

    interactive_state(projects[choice - 1])


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pdfclip.py",
        description="Copier rapidement des pages PDF en image ou en texte.",
    )
    parser.add_argument("--dir", dest="images_dir", type=Path, help="dossier des images et de l'état")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"résolution des images (défaut: {DEFAULT_DPI})")

    subparsers = parser.add_subparsers(dest="command")

    open_cmd = subparsers.add_parser("open", help="ouvrir un dossier ou PDF en mode interactif")
    open_cmd.add_argument("target", nargs="?", type=Path)

    render_cmd = subparsers.add_parser("render", help="générer les images du PDF")
    render_cmd.add_argument("pdf", type=Path)
    render_cmd.add_argument("--force", action="store_true", help="regénérer les images existantes")

    import_cmd = subparsers.add_parser("import", help="créer le dossier dédié à un PDF")
    import_cmd.add_argument("pdf", type=Path)

    for name in ["next", "previous", "current", "status"]:
        cmd = subparsers.add_parser(name)
        cmd.add_argument("target", nargs="?", type=Path)

    copy_cmd = subparsers.add_parser("copy", help="copier une page précise")
    copy_cmd.add_argument("page", type=int)
    copy_cmd.add_argument("target", nargs="?", type=Path)

    set_cmd = subparsers.add_parser("set", help="changer la page courante et la copier")
    set_cmd.add_argument("page", type=int)
    set_cmd.add_argument("target", nargs="?", type=Path)

    mode_cmd = subparsers.add_parser("mode", help="changer ou afficher le mode")
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
        print(f"dossier créé: {state['images_dir']}")
        print(f"images générées: {rendered} / {state['page_count']}")
        return

    if args.command == "render":
        state = load_state(args.pdf, args.images_dir, args.dpi)
        total, rendered = render_images(args.pdf.resolve(), Path(state["images_dir"]), args.dpi, args.force)
        state["page_count"] = total
        state["dpi"] = args.dpi
        write_state(Path(state["images_dir"]), state)
        write_global_state(state["images_dir"])
        print(f"dossier prêt: {state['images_dir']}")
        print(f"images: {total - rendered} existantes, {rendered} générées")
        return

    if args.command is None:
        choose_project(args.dpi)
        return

    state = load_target_state(getattr(args, "target", None), args.dpi)
    write_global_state(state["images_dir"])

    if args.command == "next":
        print(move_and_copy(state, 1))
    elif args.command == "previous":
        print(move_and_copy(state, -1))
    elif args.command == "current":
        print(copy_current(state))
    elif args.command == "copy":
        print(set_page(state, args.page))
    elif args.command == "set":
        print(set_page(state, args.page))
    elif args.command == "mode":
        print(set_mode(state, args.mode))
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
        print(f"erreur: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrompu", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
