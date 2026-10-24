"""Shared constants for photo-stitcher."""

import re

IMAGE_EXTENSIONS = {".jpg", ".jpeg"}   # scan file types we accept
GROUP_PATTERN = re.compile(r"^(?P<base>.+?)(?:_(?P<suffix>[ab]))?$", re.IGNORECASE)
COMPLETED_DIR_NAME = "completed"       # subfolder for finished images
SINGLE_SCANS_DIR_NAME = "single_scans"            # subfolder for single scans
REVIEWED_ORIGINALS_DIR_NAME = "reviewed_originals"  # subfolder for reviewed originals
STATE_FILENAME = ".photo_stitch_state.json"  # progress tracking file
DISPLAY_MAX_EDGE = 1600                # on-screen preview downscale cap (px)
JPEG_QUALITY = 95                      # quality used when saving stitched images
