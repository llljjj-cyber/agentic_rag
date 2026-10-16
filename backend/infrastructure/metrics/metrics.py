from prometheus_client import Counter, Histogram, Gauge

# Chat
CHAT_DURATION = Histogram(
    "meridian_chat_duration_seconds",
    "Chat stream wall time",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
)
CHAT_ERRORS = Counter(
    "meridian_chat_errors_total",
    "Chat stream failures",
    ["reason"],  # llm|timeout|other
)

# Retrieval / Agent tools
RETRIEVAL_CALLS = Counter(
    "meridian_retrieval_calls_total",
    "Agent retrieval tool calls",
    ["tool"],  # sources|chunks|inspect
)
RETRIEVAL_MATCHES = Histogram(
    "meridian_retrieval_matches",
    "Matches returned per retrieval",
    ["tool"],
    buckets=(0, 1, 2, 4, 6, 10, 20),
)

# Ingest 
INGEST_TOTAL = Counter(
    "meridian_ingest_total",
    "Source ingest outcomes",
    ["modality", "result"],  # result=ok|fail|circuit_open
)
INGEST_DURATION = Histogram(
    "meridian_ingest_duration_seconds",
    "Worker process one message",
    buckets=(1, 5, 15, 30, 60, 180, 600),
)

# Circuit breaker
CIRCUIT_OPEN_TOTAL = Counter(
    "meridian_circuit_open_total",
    "Times circuit entered OPEN",
    ["name"],  # embedding_api|mineru|llm
)
CIRCUIT_REJECTS = Counter(
    "meridian_circuit_rejects_total",
    "Calls blocked while OPEN/HALF_OPEN",
    ["name"],
)
CIRCUIT_STATE = Gauge(
    "meridian_circuit_state",
    "0=closed 1=half_open 2=open",
    ["name"],
)