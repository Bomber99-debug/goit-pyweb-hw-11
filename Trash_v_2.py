import argparse
import shutil
from argparse import Namespace
from collections.abc import Callable, Generator
from concurrent import futures
from pathlib import Path
from threading import RLock

lock = RLock()


class VerboseTask:
    def __init__(self, coun: int = 0, err: int = 0):
        self.__counter = coun
        self.__error = err

    @property
    def counter(self) -> int:
        return self.__counter

    @counter.setter
    def counter(self, count: int) -> None:
        self.__counter += count

    @property
    def error(self) -> int:
        return self.__error

    @error.setter
    def error(self, err: int) -> None:
        self.__error += err


def parse_positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None

    if number <= 0:
        raise argparse.ArgumentTypeError("workers must be > 0")
    return number


def normalize_extension(value: str) -> str:
    return value.lower().replace(".", "")


def validate_source_dir(value: str) -> Path:
    source_dir = Path(value).resolve()
    if not source_dir.is_dir():
        raise argparse.ArgumentTypeError("path source not dir")
    return source_dir


def resolve_target_dir(value: str) -> Path:
    target_dir = Path(value).resolve()
    if target_dir.exists():
        if target_dir.is_file():
            raise argparse.ArgumentTypeError("path target not dir")

    return target_dir


def parse_args() -> Namespace:
    parser = argparse.ArgumentParser(
        prog="sort_files",
        description="Сортує файли по папках",
    )

    parser.add_argument(
        "source",
        type=validate_source_dir,
        help="Шлях до вихідної папки",
    )
    parser.add_argument(
        "target",
        type=resolve_target_dir,
        nargs="?",
        default="./dist",
        help="Кінцева папка сортування",
    )
    parser.add_argument(
        "--blacklist",
        type=normalize_extension,
        nargs="+",
        help="Список розширень",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Показувати детальний вивід",
    )
    parser.add_argument(
        "--workers",
        type=parse_positive_int,
        default=4,
        help="Кількість одночасних потоків",
    )
    parser.add_argument(
        "--mode",
        choices=["copy", "move"],
        default="copy",
        help="Коміювання чи переміщення",
    )

    return parser.parse_args()


def iter_files(
    source_root: Path,
    target_root: Path | None = None,
    blacklist_extensions: list[str] | None = None,
) -> Generator[Path, None, None]:
    for entry in source_root.iterdir():
        if entry == target_root or entry.is_symlink():
            continue
        elif entry.is_dir():
            yield from iter_files(entry, target_root, blacklist_extensions)
        else:
            if blacklist_extensions and entry.suffix[1:] in blacklist_extensions:
                continue
            else:
                yield entry


def copy_file(file_task: tuple[Path, Path], obj: VerboseTask) -> None:
    """Створює цільову директорію та копіює файл у фінальний шлях."""
    source_file, destination_file = file_task

    destination_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, destination_file)
    with lock:
        obj.counter = 1


def move_file(file_task: tuple[Path, Path], obj: VerboseTask) -> None:
    """Створює цільову директорію та переміщує файл у фінальний шлях."""
    source_file, destination_file = file_task

    destination_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source_file, destination_file)
    with lock:
        obj.counter = 1


def build_destination_path(source_file: Path, target_root: Path) -> Path:
    """Будує цільовий шлях для файла на основі його розширення."""
    if source_file.suffix:
        extension_dir = source_file.suffix[1:].lower()
    else:
        extension_dir = "no_extension"

    return target_root / extension_dir / source_file.name


def collect_reserved_paths(target_root: Path) -> set[Path]:
    reserved_paths: set[Path] = set()
    for file_path in iter_files(target_root):
        reserved_paths.add(file_path)

    return reserved_paths


def build_unique_destination_path(
    source_file: Path,
    target_root: Path,
    reserved_paths: set[Path],
) -> Path:
    base_name = source_file.stem
    suffix = source_file.suffix
    counter = 1

    while True:
        candidate_file_name = Path(f"{base_name} ({counter}){suffix}")
        destination_file = build_destination_path(candidate_file_name, target_root)

        if destination_file not in reserved_paths:
            reserved_paths.add(destination_file)
            break

        counter += 1

    return destination_file


def build_file_task(
    source_file: Path,
    target_root: Path,
    reserved_paths: set[Path],
) -> tuple[Path, Path]:
    destination_file = build_destination_path(source_file, target_root)

    if destination_file in reserved_paths:
        destination_file = build_unique_destination_path(
            source_file,
            target_root,
            reserved_paths,
        )
    else:
        reserved_paths.add(destination_file)

    return (source_file, destination_file)


def main() -> None:
    args = parse_args()

    file_operations: dict[str, Callable[[tuple[Path, Path], VerboseTask], None]] = {
        "copy": copy_file,
        "move": move_file,
    }

    source_root: Path = args.source
    target_root: Path = args.target
    blacklist_extensions: list[str] | None = (
        list(args.blacklist) if args.blacklist else None
    )

    verbose_task = VerboseTask()

    reserved_paths: set[Path] = (
        collect_reserved_paths(target_root) if target_root.is_dir() else set()
    )

    max_workers: int = args.workers
    selected_operation: Callable[[tuple[Path, Path], VerboseTask], None] = (
        file_operations[args.mode]
    )

    with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for source_file in iter_files(source_root, target_root, blacklist_extensions):
            file_task = build_file_task(
                source_file=source_file,
                target_root=target_root,
                reserved_paths=reserved_paths,
            )

            # submit запускає задачу в пулі потоків.
            # Поки що futures не зберігаються і результати не перевіряються.
            executor.submit(selected_operation, file_task, verbose_task)

    print(
        f"Файлів сокпійовано/переміщено: {verbose_task.counter}\n"
        f"Помилок при копіювані: {verbose_task.error}"
    )


if __name__ == "__main__":
    main()
