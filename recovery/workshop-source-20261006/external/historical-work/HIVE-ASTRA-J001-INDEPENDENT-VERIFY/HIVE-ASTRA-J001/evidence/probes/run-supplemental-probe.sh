#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: JAVA=/path/to/java JAVAC=/path/to/javac $0 <actual-compiled-formatter-classpath>" >&2
  exit 2
fi
probe_dir=$(cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$probe_dir/classes"
if [ -n "${JAVAC:-}" ]; then
  "$JAVAC" -encoding UTF-8 -d "$probe_dir/classes" "$probe_dir/BoundLineSupplementalProbe.java"
else
  "${JAVA:-java}" com.sun.tools.javac.Main -encoding UTF-8 -d "$probe_dir/classes" "$probe_dir/BoundLineSupplementalProbe.java"
fi
"${JAVA:-java}" -cp "$probe_dir/classes:$1" BoundLineSupplementalProbe
