"""Hive Compressor MVP."""

from .compressor import CompressionError, compress_records

__all__ = ["CompressionError", "compress_records"]
__version__ = "0.1.0"
