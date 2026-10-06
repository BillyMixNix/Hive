"""Conservative, fail-closed spending for the single 2026-09-09 packet comparison.

Rates verified at https://developers.openai.com/api/docs/models/gpt-5.6-luna
on 2026-09-09. All arithmetic is integer billionths of a US dollar (nanoUSD).
This bounds API token charges, not unrelated activity on the user's account.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading


MODEL = "gpt-5.6-luna"
CONTEXT_TOKENS = 1_050_000
# Published input $0.20/M * 2 (long context) * 1.25 (cache writes).
# Published output $1.20/M * 1.5 (long context). Apply both maximum
# rates to every reported token, regardless of actual discount eligibility.
INPUT_NUSD = 500
OUTPUT_NUSD = 1800
LIMIT_NUSD = 5_000_000_000
VALID_UNTIL = datetime(2026, 9, 10, tzinfo=timezone.utc)


class SpendingGuard:
    def __init__(self, journal, *, model=MODEL, max_output_tokens=4096, now=None,
                 prior_upper_nano_usd=0):
        self._clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
        instant = self._clock()
        if instant >= VALID_UNTIL or instant < datetime(2026, 9, 9, tzinfo=timezone.utc):
            raise ValueError("trial pricing authorization has expired or is not yet valid")
        if model != MODEL or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32768:
            raise ValueError("spending guard requires its verified model and output bounds")
        if type(prior_upper_nano_usd) is not int or not 0 <= prior_upper_nano_usd <= LIMIT_NUSD:
            raise ValueError("prior spending must be a bounded integer charge reservation")
        self.prior = prior_upper_nano_usd
        self.model, self.max_output_tokens = model, max_output_tokens
        self.reservation = CONTEXT_TOKENS * INPUT_NUSD + max_output_tokens * OUTPUT_NUSD
        self.committed = self.pending = self.requests = 0
        self.blocked = False
        self.lock = threading.Lock()
        # Exclusive creation refuses local process restarts. The workflow also
        # refuses reruns and all push events except its one authorized launch.
        self.journal = Path(journal).open("x", encoding="utf-8")
        self._record("opened")

    @property
    def identity(self):
        return {"model": self.model, "limit_nano_usd": LIMIT_NUSD,
                "prior_upper_nano_usd": self.prior,
                "input_nano_usd_per_token": INPUT_NUSD,
                "output_nano_usd_per_token": OUTPUT_NUSD,
                "input_reservation_tokens": CONTEXT_TOKENS,
                "max_output_tokens": self.max_output_tokens,
                "valid_until": VALID_UNTIL.isoformat(),
                "method": "full-context reservation; conservative measured-usage settlement",
                "source": "https://developers.openai.com/api/docs/models/gpt-5.6-luna"}

    def snapshot(self):
        return {"limit_nano_usd": LIMIT_NUSD,
                "prior_upper_nano_usd": self.prior,
                "measured_usage_upper_nano_usd": self.committed,
                "unresolved_reservation_nano_usd": self.pending,
                "total_upper_nano_usd": self.prior + self.committed + self.pending,
                "requests_reserved": self.requests, "blocked": self.blocked}

    def _record(self, event):
        self.journal.write(json.dumps({"event": event, **self.snapshot()}, sort_keys=True) + "\n")
        self.journal.flush()
        os.fsync(self.journal.fileno())

    def reserve(self):
        with self.lock:
            if self._clock() >= VALID_UNTIL:
                raise RuntimeError("packet comparison pricing verification expired")
            if self.blocked or self.pending:
                raise RuntimeError("spending guard stopped after an unresolved request")
            if self.prior + self.committed + self.reservation > LIMIT_NUSD:
                raise RuntimeError("remaining trial budget cannot cover another full request")
            self.pending = self.reservation
            self.requests += 1
            self._record("reserved_before_network")

    def settle(self, model, input_tokens, output_tokens, service_tier):
        with self.lock:
            if (not self.pending or model != self.model or service_tier != "default"
                    or type(input_tokens) is not int or not 0 <= input_tokens <= CONTEXT_TOKENS
                    or type(output_tokens) is not int or not 0 <= output_tokens <= self.max_output_tokens):
                raise ValueError("cannot safely settle provider usage against the spending reservation")
            charge = input_tokens * INPUT_NUSD + output_tokens * OUTPUT_NUSD
            if charge > self.pending:
                raise ValueError("provider usage exceeds the spending reservation")
            self.committed += charge
            self.pending = 0
            self._record("settled_from_measured_usage")

    def fail(self):
        with self.lock:
            self.blocked = True
            self._record("stopped_without_retry")

    def close(self):
        self.journal.close()

