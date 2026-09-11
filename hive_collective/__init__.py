"""First-principles cognitive collective research prototype.

This package is intentionally independent of Hive's legacy runtime. It exists to
experiment with the hypothesis that bounded cognitive operations can be composed
into a useful collective state through explicit artifacts and compilation.
"""

from .artifact import CognitiveArtifact
from .state import CollectiveState
from .node import CognitiveNode
from .compiler import CollectiveCompiler

__all__ = ["CognitiveArtifact", "CollectiveState", "CognitiveNode", "CollectiveCompiler"]
