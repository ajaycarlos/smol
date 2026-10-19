# smol core engine — file shrinking pipeline
# NO UI imports. Must run headless.

from smol.core.audio import shrink_audio
from smol.core.image import shrink_image
from smol.core.paths import output_path
from smol.core.pdf import shrink_pdf
from smol.core.result import Result
from smol.core.router import detect_file_type, shrink_file
from smol.core.size import format_size, parse_size
from smol.core.video import shrink_video

__all__ = [
    "Result",
    "detect_file_type",
    "format_size",
    "output_path",
    "parse_size",
    "shrink_audio",
    "shrink_file",
    "shrink_image",
    "shrink_pdf",
    "shrink_video",
]

