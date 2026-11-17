JOB_SCHEMA = "argiloteca.drx.external_job.v1"
SUPPORTED_JOB_ENGINES = frozenset({"gsas2", "dara"})
JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
