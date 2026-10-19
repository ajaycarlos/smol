# smol core engine — file shrinking pipeline
# NO UI imports. Must run headless.

from smol.core.image import shrink_image
from smol.core.paths import output_path
from smol.core.result import Result
from smol.core.size import format_size, parse_size

__all__ = ["Result", "format_size", "output_path", "parse_size", "shrink_image"]
