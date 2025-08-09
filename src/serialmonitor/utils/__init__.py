from pathlib import Path


def resolve(*names: str):
    return str(Path(__file__).parent.joinpath(*('..', *names)))


def printable_bytes(byte_string: bytes) -> str:
    return ''.join(
        chr(b) if chr(b).isprintable() or b in (9, 10, 13) else '*'  # Printable ASCII range + CRLF
        for b in byte_string
    )


__all__ = [
    'resolve',
    'printable_bytes'
]
