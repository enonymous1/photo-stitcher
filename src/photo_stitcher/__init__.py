"""photo-stitcher: review, rotate, and stitch FastFoto-style photo scans."""

__version__ = "0.1.0"

from .constants import (
    COMPLETED_DIR_NAME,
    JPEG_QUALITY,
    SINGLE_SCANS_DIR_NAME,
    REVIEWED_ORIGINALS_DIR_NAME,
)
from .grouping import (
    PhotoGroup,
    move_single_scans,
    move_reviewed_originals,
    single_scan_groups,
    reviewed_groups,
    scan_directory,
    unique_output_path,
)
from .imaging import load_image, stitch_images
from .state import ReviewState

__all__ = [
    "__version__",
    "COMPLETED_DIR_NAME",
    "JPEG_QUALITY",
    "SINGLE_SCANS_DIR_NAME",
    "REVIEWED_ORIGINALS_DIR_NAME",
    "PhotoGroup",
    "ReviewState",
    "load_image",
    "move_single_scans",
    "move_reviewed_originals",
    "single_scan_groups",
    "reviewed_groups",
    "scan_directory",
    "stitch_images",
    "unique_output_path",
]
