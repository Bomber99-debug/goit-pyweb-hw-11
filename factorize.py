import multiprocessing
import time
from multiprocessing import Pool


def factorize(*numbers: int) -> list[list[int]]:
    """Синхронно знаходить дільники для кожного переданого числа."""
    results: list[list[int]] = list()

    for number in numbers:
        divisors: list[int] = list()

        for divisor in range(1, number + 1):
            if number % divisor == 0:
                divisors.append(divisor)

        results.append(divisors)

    return results


def factorize_single(number: int) -> list[int]:
    """Знаходить дільники одного числа для використання в Pool.map."""
    divisors: list[int] = list()

    for divisor in range(1, number + 1):
        if number % divisor == 0:
            divisors.append(divisor)

    return divisors


def main() -> None:
    sync_execution_times: list[float] = list()
    process_execution_times: list[float] = list()

    test_numbers: tuple[int, int, int, int] = (128, 255, 99999, 10651060)
    with Pool(processes=multiprocessing.cpu_count()) as pool:
        for _ in range(10):
            # Замір синхронного виконання.
            start_time: float = time.perf_counter()
            a, b, c, d = factorize(*test_numbers)
            sync_elapsed: float = time.perf_counter() - start_time
            sync_execution_times.append(sync_elapsed)

            assert a == [1, 2, 4, 8, 16, 32, 64, 128]
            assert b == [1, 3, 5, 15, 17, 51, 85, 255]
            assert c == [1, 3, 9, 41, 123, 271, 369, 813, 2439, 11111, 33333, 99999]
            assert d == [
                1,
                2,
                4,
                5,
                7,
                10,
                14,
                20,
                28,
                35,
                70,
                140,
                76079,
                152158,
                304316,
                380395,
                532553,
                760790,
                1065106,
                1521580,
                2130212,
                2662765,
                5325530,
                10651060,
            ]

            # Замір багатопроцесорного виконання.
            start_time = time.perf_counter()

            result: list[list[int]] = pool.map(factorize_single, test_numbers)
            process_elapsed: float = time.perf_counter() - start_time
            process_execution_times.append(process_elapsed)

            a, b, c, d = result

            assert a == [1, 2, 4, 8, 16, 32, 64, 128]
            assert b == [1, 3, 5, 15, 17, 51, 85, 255]
            assert c == [1, 3, 9, 41, 123, 271, 369, 813, 2439, 11111, 33333, 99999]
            assert d == [
                1,
                2,
                4,
                5,
                7,
                10,
                14,
                20,
                28,
                35,
                70,
                140,
                76079,
                152158,
                304316,
                380395,
                532553,
                760790,
                1065106,
                1521580,
                2130212,
                2662765,
                5325530,
                10651060,
            ]

    print(
        "Синхронне виконання:\n"
        f"- мінімальний час: {min(sync_execution_times)}\n"
        f"- середній час: {sum(sync_execution_times) / len(sync_execution_times)}\n"
        f"- максимальний час: {max(sync_execution_times)}\n"
        "Багатопроцесорне виконання:\n"
        f"- мінімальний час: {min(process_execution_times)}\n"
        f"- середній час: {sum(process_execution_times)/len(process_execution_times)}\n"
        f"- максимальний час: {max(process_execution_times)}\n"
    )


if __name__ == "__main__":
    main()
