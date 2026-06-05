import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review_migrator.gui import ReviewMigratorGui, main


def smoke_test() -> None:
    if sys.platform != "win32":
        return

    import paramiko
    from tkinter import Tk

    _ = paramiko.Transport
    root = Tk()
    root.withdraw()
    ReviewMigratorGui(root)
    root.update_idletasks()
    root.destroy()


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        smoke_test()
        raise SystemExit(0)
    main()
