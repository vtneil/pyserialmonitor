import sys
import logging
from .app import SerialApp


def __remove_stream_log():
    for handler in logging.root.handlers[:]:
        if isinstance(handler, logging.StreamHandler):
            logging.root.removeHandler(handler)


def main() -> int:
    app = SerialApp()
    __remove_stream_log()
    app.run()
    return app.return_code or 0


if __name__ == '__main__':
    sys.exit(main())
