import sys
from .app import SerialApp


def main() -> int:
    app = SerialApp()
    app.run()
    return app.return_code or 0


if __name__ == '__main__':
    sys.exit(main())
