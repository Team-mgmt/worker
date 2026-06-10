import re
from typing import Literal

POSITIONS: list[Literal["LT", "RT", "RB", "LB"]] = ["LT", "RT", "RB", "LB"]

JOB_TIMEOUT_MINUTES = 5
JOB_MAX_RETRIES = 3
WORKER_HEARTBEAT_INTERVAL_SECONDS = 3

BASE64_URL_REGEX = re.compile(r"^[A-Za-z0-9_-]+$")

# Metadata area whose stringified value is the exam taker's name. Matched
# against ExamPaperAreaType.name verbatim.
EXAM_NAME_AREA_TYPE = "EXAM_NAME"

# Sentinel "nil" UUID written into worker-seeded name-history entries.
NIL_UUID = "00000000-0000-0000-0000-000000000000"

# `source` literal for worker-authored nameHistory entries. NOT a Scansource
# DB enum value (that enum is STUDENT/TEACHER only); this only ever lives in
# the submission.metadata JSONB.
NAME_HISTORY_SOURCE_WORKER = "WORKER"
