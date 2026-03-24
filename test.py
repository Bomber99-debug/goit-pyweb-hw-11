from pathlib import Path

path_1 = Path("/picture/")
path_2 = Path("./picture/wallpaper").resolve()

print(path_1 == path_2)
print(path_2)
