"""Hive Compressor MVP."""

from .adapter import SourceEvidence, build_adapter_packet, preserve_source, recover_source
from .coding_agent import adapt_coding_session
from .compressor import CompressionError, compress_records

__all__ = [
    "CompressionError",
    "SourceEvidence",
    "adapt_coding_session",
    "build_adapter_packet",
    "compress_records",
    "preserve_source",
    "recover_source",
]
__version__ = "0.2.0"
