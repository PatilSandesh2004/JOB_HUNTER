"""Read-only IMAP access to the user's own mailbox (Python's standard imaplib; no third-party service).

The folder is opened read-only and bodies are fetched with BODY.PEEK, so nothing is marked as read.
Headers are read first; the caller decides which messages are worth downloading in full.
"""

import asyncio
import contextlib
import email
import hashlib
import imaplib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

MAX_BODY_CHARS = 2_000_000
_UID_RE = re.compile(rb"UID (\d+)")

# (message key, From, Subject) -> download the full message?
WantFn = Callable[[str, str, str], bool]


class MailError(Exception):
    """Login, folder or connection problem; shown to the user as is."""


@dataclass
class MailMessage:
    key: str  # sha256 of the Message-ID: stable, and reveals nothing about the email
    sender: str
    subject: str
    received_at: datetime | None
    html: str
    text: str


class ImapReader:
    def __init__(self, host: str, port: int, user: str, password: str, folder: str = "INBOX", timeout: float = 30):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.folder, self.timeout = folder, timeout

    async def fetch(self, since_days: int, limit: int, want: WantFn) -> list[MailMessage]:
        return await asyncio.to_thread(self._fetch, since_days, limit, want)

    def _fetch(self, since_days: int, limit: int, want: WantFn) -> list[MailMessage]:
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        except OSError as exc:
            raise MailError(f"Cannot connect to {self.host}:{self.port}: {exc}") from exc
        try:
            try:
                conn.login(self.user, self.password)
            except imaplib.IMAP4.error as exc:
                raise MailError(f"Login failed for {self.user}. Gmail needs an app password. ({exc})") from exc
            status, _ = conn.select(f'"{self.folder}"', readonly=True)
            if status != "OK":
                raise MailError(f"Mail folder '{self.folder}' not found")
            since = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%d-%b-%Y")
            _, data = conn.uid("SEARCH", None, "SINCE", since)
            uids = (data[0] or b"").split()[-limit:]
            if not uids:
                return []

            _, data = conn.uid(
                "FETCH", b",".join(uids).decode(), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)])"
            )
            wanted: list[bytes] = []
            for uid, raw in _payloads(data):
                headers = email.message_from_bytes(raw, policy=policy.default)
                if want(message_key(headers, uid), str(headers.get("From", "")), str(headers.get("Subject", ""))):
                    wanted.append(uid)

            messages: list[MailMessage] = []
            for start in range(0, len(wanted), 25):
                batch = b",".join(wanted[start : start + 25]).decode()
                _, data = conn.uid("FETCH", batch, "(BODY.PEEK[])")
                messages += [to_mail_message(raw, uid) for uid, raw in _payloads(data)]
            return messages
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(f"Mail server error: {exc}") from exc
        finally:
            with contextlib.suppress(Exception):
                conn.logout()


def _payloads(data: list) -> list[tuple[bytes, bytes]]:
    """imaplib FETCH responses -> [(uid, payload)]; items are (meta, payload) tuples mixed with b')'."""
    out = []
    for item in data or []:
        if isinstance(item, tuple) and len(item) == 2:
            match = _UID_RE.search(item[0])
            if match:
                out.append((match.group(1), item[1]))
    return out


def message_key(message: EmailMessage, uid: bytes = b"") -> str:
    message_id = str(message.get("Message-ID", "")).strip()
    basis = message_id or f"{uid!r}|{message.get('Date', '')}|{message.get('Subject', '')}"
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()


def to_mail_message(raw: bytes, uid: bytes = b"") -> MailMessage:
    message = email.message_from_bytes(raw, policy=policy.default)
    html_parts, text_parts = [], []
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError):
            continue
        if not isinstance(content, str):
            continue
        if part.get_content_type() == "text/html":
            html_parts.append(content)
        elif part.get_content_type() == "text/plain":
            text_parts.append(content)
    try:
        received = parsedate_to_datetime(str(message.get("Date", "")))
        received = received if received.tzinfo else received.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        received = None
    return MailMessage(
        key=message_key(message, uid),
        sender=str(message.get("From", "")),
        subject=str(message.get("Subject", "")),
        received_at=received,
        html="\n".join(html_parts)[:MAX_BODY_CHARS],
        text="\n".join(text_parts)[:MAX_BODY_CHARS],
    )
