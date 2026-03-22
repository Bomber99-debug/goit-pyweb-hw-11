import shutil
from concurrent import futures
from pathlib import Path
from sys import argv


def collect_files(root_path: Path) -> list[Path]:
    """Рекурсивно збирає всі файли з директорії та її піддиректорій."""

    def walk_directory(current_path: Path) -> list[Path]:
        """Обходить поточну директорію та повертає список знайдених файлів."""
        collected_files: list[Path] = []

        for entry in current_path.iterdir():
            if entry.is_dir():
                nested_files = walk_directory(entry)
                collected_files.extend(nested_files)
            else:
                collected_files.append(entry)

        return collected_files

    return walk_directory(root_path)


def copy_file(copy_task: tuple[Path, Path]) -> None:
    """Створює цільову директорію та копіює файл у фінальний шлях."""
    source_path, destination_path = copy_task

    # Перед копіюванням гарантуємо, що цільова директорія вже існує.
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source_path, destination_path)


def build_copy_plan(
    source_files: list[Path], target_root: Path
) -> list[tuple[Path, Path]]:
    """Формує план копіювання з унікальними цільовими шляхами."""
    copy_plan: list[tuple[Path, Path]] = []

    reserved_destinations: set[Path] = (
        set() if not target_root.is_dir() else set(collect_files(target_root))
    )

    def build_destination_path(source_path: Path, file_name: str) -> Path:
        """Будує цільовий шлях для файла на основі його розширення."""
        if source_path.suffix:
            extension_folder = source_path.suffix[1:].lower()
        else:
            extension_folder = "no_extension"

        return target_root / extension_folder / file_name

    for source_path in source_files:
        destination_path = build_destination_path(source_path, source_path.name)

        if destination_path not in reserved_destinations:
            reserved_destinations.add(destination_path)
            copy_plan.append((source_path, destination_path))
            continue

        base_name = source_path.stem
        suffix = source_path.suffix
        counter = 1

        while True:
            new_file_name = f"{base_name} ({counter}){suffix}"
            destination_path = build_destination_path(source_path, new_file_name)

            if destination_path not in reserved_destinations:
                reserved_destinations.add(destination_path)
                copy_plan.append((source_path, destination_path))
                break

            counter += 1

    return copy_plan


def parse_args(args: list[str]) -> tuple[Path, Path]:
    """Повертає source і target шляхи з аргументів командного рядка."""
    if len(args) not in (2, 3):
        raise SystemExit("Usage: script.py <source> [target]")

    source_root = Path(args[1]).absolute()
    if not source_root.is_dir():
        raise SystemExit(f"Source directory not found: {source_root}")

    if len(args) == 3:
        target_root = Path(args[2]).absolute()
    else:
        target_root = Path("./dist").absolute()

    return source_root, target_root


def main() -> None:
    """Збирає файли, будує план копіювання та запускає копіювання у кілька потоків."""
    MAX_WORKERS = 4
    source_root, target_root = parse_args(argv)

    source_files = collect_files(source_root)
    copy_plan = build_copy_plan(source_files, target_root)

    with futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(copy_file, copy_plan)


if __name__ == "__main__":
    main()
