import contextlib
import io
import os
from typing import BinaryIO, Generator, Union

AudioSource = Union[str, os.PathLike, BinaryIO]


@contextlib.contextmanager
def open_audio_source(source: AudioSource) -> Generator[BinaryIO, None, None]:
    """Yield a readable binary stream regardless of whether source is a path or buffer."""
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as handle:
            yield handle
        return

    if hasattr(source, "read"):
        stream = source
        remember_pos = None
        try:
            if hasattr(stream, "tell"):
                try:
                    remember_pos = stream.tell()
                except (OSError, io.UnsupportedOperation):
                    remember_pos = None
            if hasattr(stream, "seek"):
                try:
                    stream.seek(0)
                except (OSError, io.UnsupportedOperation):
                    pass
            yield stream
        finally:
            if remember_pos is not None and hasattr(stream, "seek"):
                try:
                    stream.seek(remember_pos)
                except (OSError, io.UnsupportedOperation):
                    pass
        return

    raise TypeError("Audio source must be a path or a binary stream with a read() method.")
