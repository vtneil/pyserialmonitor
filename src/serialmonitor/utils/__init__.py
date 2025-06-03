from pathlib import Path

def resolve(*names: str):
    return str(Path(__file__).parent.joinpath(*('..', *names)))


__all__ = [
    'resolve',
]