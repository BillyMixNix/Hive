"""Hive Compressor MVP."""

from .adapter import SourceEvidence, build_adapter_packet, preserve_source, recover_source
from .compressor import CompressionError, compress_records

__all__ = [
    "CompressionError",
    "SourceEvidence",
    "build_adapter_packet",
    "compress_records",
    "preserve_source",
    "recover_source",
]
__version__ = "0.1.0"
