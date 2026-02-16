MIN_PIXELS=3136
MAX_PIXELS=1000000           # Optimized default for CPU inference (~1276 visual tokens)
MAX_PIXELS_FULL=11289600     # Original full-resolution limit (use for high-fidelity mode)
IMAGE_FACTOR=28

DEFAULT_DPI = 150            # Optimized default (was 200); sufficient for standard pricelist text
DEFAULT_MAX_TOKENS = 4096    # Optimized default (was 16384); sufficient for single-table pages

image_extensions = {'.jpg', '.jpeg', '.png'}
excel_extensions = {'.xlsx', '.xls'}
