import argparse
import logging
import shutil
from argparse import Namespace
from collections.abc import Callable, Generator
from concurrent import futures
from pathlib import Path
from queue import Queue
from threading import RLock, Thread

log_queue: Queue[str | None] = Queue()
verbose_queue: Queue[tuple[Path, Path] | None] = Queue()
lock = RLock()


class TaskStats:
    """Зберігає кількість оброблених файлів і кількість помилок."""

    def __init__(self, counter: int = 0, error: int = 0) -> None:
        self.__counter = counter
        self.__error = error

    @property
    def counter(self) -> int:
        return self.__counter

    @counter.setter
    def counter(self, count: int) -> None:
        self.__counter = count

    @property
    def error(self) -> int:
        return self.__error

    @error.setter
    def error(self, err: int) -> None:
        self.__error = err


def parse_positive_int(value: str) -> int:
    """Перетворює рядок у додатне ціле число для аргументу workers."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None

    if number <= 0:
        raise argparse.ArgumentTypeError("workers must be > 0")
    return number


def normalize_suffix(value: str | list[str]) -> str:
    """Нормалізує розширення: нижній регістр без крапки."""
    if not isinstance(value, str):
        value = "".join(value)

    return value.lower().lstrip(".")


def validate_source_dir(value: str) -> Path:
    """Перевіряє, що source існує і є директорією."""
    source_dir = Path(value).resolve()
    if not source_dir.is_dir():
        raise argparse.ArgumentTypeError("path source not dir")
    return source_dir


def validate_target_dir(value: str) -> Path:
    """Повертає шлях до target і перевіряє, що це не файл."""
    target_dir = Path(value).resolve()
    if target_dir.exists():
        if target_dir.is_file():
            raise argparse.ArgumentTypeError("path target not dir")

    return target_dir


def parse_args() -> Namespace:
    """Налаштовує CLI-аргументи та повертає результат парсингу."""
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
        type=validate_target_dir,
        nargs="?",
        default="./dist",
        help="Кінцева папка сортування",
    )
    parser.add_argument(
        "--blacklist",
        type=normalize_suffix,
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
        help="Копіювання чи переміщення",
    )

    return parser.parse_args()


def iter_files(
    source_root: Path,
    target_root: Path | None = None,
    blacklist_extensions: list[str] | None = None,
) -> Generator[Path, None, None]:
    """Рекурсивно проходить по директорії та повертає файли для обробки."""
    for entry in source_root.iterdir():
        if entry == target_root or entry.is_symlink():
            continue
        elif entry.is_dir():
            yield from iter_files(entry, target_root, blacklist_extensions)
        else:
            entry_suffix = normalize_suffix(entry.suffixes)
            if blacklist_extensions and entry_suffix in blacklist_extensions:
                continue
            yield entry


def write_verbose_log(log_file_path: Path) -> None:
    """Записує у файл інформацію про copied/moved файли у verbose-режимі."""
    with open(log_file_path, "a", encoding="utf-8") as file:
        while True:
            item = verbose_queue.get()
            if item is None:
                break
            source_path, destination_path = item
            file.write(f"{source_path} | {destination_path}\n")


def copy_file(
    file_task: tuple[Path, Path],
    stats: TaskStats,
    source_root: Path,
    target_root: Path,
    verbose: bool,
) -> None:
    """Копіює файл у підготовлений цільовий шлях."""
    source_file, destination_file = file_task

    try:
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        if verbose:
            verbose_queue.put(
                (
                    source_file.relative_to(source_root),
                    destination_file.relative_to(target_root),
                )
            )
        with lock:
            stats.counter += 1
    except OSError as error:
        log_queue.put(f"{error} - copy file: {source_file}")
        with lock:
            stats.error += 1


def move_file(
    file_task: tuple[Path, Path],
    stats: TaskStats,
    source_root: Path,
    target_root: Path,
    verbose: bool,
) -> None:
    """Переміщує файл у підготовлений цільовий шлях."""
    source_file, destination_file = file_task
    try:
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source_file, destination_file)
        if verbose:
            verbose_queue.put(
                (
                    source_file.relative_to(source_root),
                    destination_file.relative_to(target_root),
                )
            )
        with lock:
            stats.counter += 1
    except OSError as error:
        log_queue.put(f"{error} - move file: {source_file}")
        with lock:
            stats.error += 1


def build_destination_path(source_file: Path, target_root: Path) -> Path:
    """Будує цільовий шлях для файла на основі його розширення."""
    if source_file.suffixes:
        extension_dir = normalize_suffix(source_file.suffixes)
    else:
        extension_dir = "no_extension"

    return target_root / extension_dir / source_file.name


def collect_reserved_paths(target_root: Path) -> set[Path]:
    """Збирає всі вже зайняті шляхи в target, щоб уникати конфліктів імен."""
    return set(iter_files(target_root))


def build_unique_destination_path(
    source_file: Path,
    target_root: Path,
    reserved_paths: set[Path],
) -> Path:
    """Підбирає унікальне ім'я файла, якщо цільовий шлях вже зайнятий."""

    suffix = normalize_suffix(source_file.suffixes)
    full_suffix = f".{suffix}" if suffix else ""

    name = source_file.name

    if full_suffix and name.endswith(full_suffix):
        base_name = name[: -len(full_suffix)]
    else:
        base_name = name

    counter = 1

    while True:
        candidate_name = Path(f"{base_name} ({counter}).{suffix}")
        destination_file = build_destination_path(candidate_name, target_root)

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
    """Формує пару: вихідний файл і фінальний шлях призначення."""
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


def write_error_log() -> None:
    """Читає повідомлення з черги і записує їх у logging."""
    while True:
        message = log_queue.get()
        if message is None:
            break
        logging.error(message)


def main() -> None:
    logging.basicConfig(
        filename="logging.log",
        filemode="a",
        encoding="utf-8",
        level=logging.ERROR,
        format="%(asctime)s - %(levelname)s - %(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    Path("./logging.log").touch(exist_ok=True)

    args = parse_args()

    file_operations: dict[
        str, Callable[[tuple[Path, Path], TaskStats, Path, Path, bool], None]
    ] = {
        "copy": copy_file,
        "move": move_file,
    }

    source_root: Path = args.source
    target_root: Path = args.target
    verbose: bool = args.verbose

    blacklist_extensions: list[str] | None = (
        list(args.blacklist) if args.blacklist else None
    )

    if verbose:
        verbose_log_path = Path("./log_file.txt")
        verbose_log_path.touch(exist_ok=True)
        verbose_thread = Thread(target=write_verbose_log, args=(verbose_log_path,))
        verbose_thread.start()

    log_thread = Thread(target=write_error_log)
    log_thread.start()

    stats = TaskStats()

    reserved_paths: set[Path] = (
        collect_reserved_paths(target_root) if target_root.is_dir() else set()
    )

    max_workers: int = args.workers
    selected_operation: Callable[
        [tuple[Path, Path], TaskStats, Path, Path, bool], None
    ] = file_operations[args.mode]

    with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for source_file in iter_files(source_root, target_root, blacklist_extensions):
            file_task = build_file_task(
                source_file=source_file,
                target_root=target_root,
                reserved_paths=reserved_paths,
            )

            # Запускає копіювання або переміщення файла у пулі потоків.
            executor.submit(
                selected_operation,
                file_task,
                stats,
                source_root,
                target_root,
                verbose,
            )

    log_queue.put(None)
    log_thread.join()

    if verbose:
        verbose_queue.put(None)
        verbose_thread.join()

    print(
        f"Файлів сокпійовано/переміщено: {stats.counter}\n"
        f"Помилок при копіювані: {stats.error}"
    )


if __name__ == "__main__":
    main()
