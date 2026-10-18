import email.errors
import email.header
import email.utils
from datetime import datetime
from email.message import Message
from enum import Enum

from pydantic import BaseModel


class Header(str, Enum):
    SUBJECT_HEADER = "subject"
    FROM_HEADER = "from"
    TO_HEADER = "to"
    DELIVERED_TO_HEADER = (
        "Delivered-To"  # Used in mailing lists instead of the "to" header.
    )
    DATE_HEADER = "date"
    MESSAGE_ID_HEADER = "Message-ID"
    CC_HEADER = "cc"


class EmailHeaders(BaseModel):
    """
    Model for email headers extracted from IMAP messages.

    Every header but the subject may be missing; the connector falls back
    (content-hash id, server receive time, no sender) instead of failing.
    """

    id: str | None
    subject: str
    sender: str | None
    recipients: str | None
    cc: str | None
    date: datetime | None

    @classmethod
    def from_email_msg(cls, email_msg: Message) -> "EmailHeaders":
        def _decode(header: str, default: str | None = None) -> str | None:
            value = email_msg.get(header, default)
            if not value:
                return None

            # A header can mix plain text and several encoded words, e.g.
            # `Re: =?utf-8?b?...?=` or `=?utf-8?b?...?= <addr>`; join them all.
            try:
                chunks = email.header.decode_header(value)
            except email.errors.HeaderParseError:
                return str(value)
            parts: list[str] = []
            for chunk, charset in chunks:
                if isinstance(chunk, str):
                    parts.append(chunk)
                    continue
                # Raw 8-bit headers come back as `unknown-8bit`; in practice
                # such mail is UTF-8.
                if not charset or charset == "unknown-8bit":
                    charset = "utf-8"
                try:
                    parts.append(chunk.decode(charset, errors="replace"))
                except LookupError:
                    parts.append(chunk.decode("utf-8", errors="replace"))
            return "".join(parts)

        def _parse_date(date_str: str | None) -> datetime | None:
            if not date_str:
                return None
            try:
                return email.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                return None

        message_id = _decode(header=Header.MESSAGE_ID_HEADER)
        # It's possible for the subject line to not exist or be an empty string.
        subject = _decode(header=Header.SUBJECT_HEADER) or "Unknown Subject"
        from_ = _decode(header=Header.FROM_HEADER)
        to = _decode(header=Header.TO_HEADER)
        if not to:
            to = _decode(header=Header.DELIVERED_TO_HEADER)
        date_str = _decode(header=Header.DATE_HEADER)
        date = _parse_date(date_str=date_str)

        return cls.model_validate(
            {
                "id": message_id,
                "subject": subject,
                "sender": from_,
                "recipients": to,
                "cc": _decode(header=Header.CC_HEADER),
                "date": date,
            }
        )
