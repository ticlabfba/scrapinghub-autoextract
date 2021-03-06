# -*- coding: utf-8 -*-
import logging
import re
from typing import Optional

from aiohttp import ClientResponseError
from tenacity import RetryError

logger = logging.getLogger(__name__)


class DomainOccupied:

    DOMAIN_OCCUPIED_REGEX = re.compile(
        r".*domain (.+) is occupied, please retry in (.+) seconds.*",
        re.IGNORECASE
    )

    DEFAULT_RETRY_SECONDS = 5 * 60  # 5 minutes

    def __init__(self, domain: str, retry_seconds: float):
        self.domain = domain
        self.retry_seconds = retry_seconds

    @classmethod
    def from_message(cls, message: str) -> Optional["DomainOccupied"]:
        match = cls.DOMAIN_OCCUPIED_REGEX.match(message)
        if not match:
            return None

        domain = match.group(1)

        try:
            retry_seconds = float(match.group(2))
        except ValueError:
            logger.warning(
                f"Could not extract retry seconds "
                f"from Domain Occupied error message: {message}"
            )
            retry_seconds = cls.DEFAULT_RETRY_SECONDS

        return cls(domain=domain, retry_seconds=retry_seconds)


class RequestError(ClientResponseError):
    """ Exception which is raised when Request-level error is returned.
    In contrast with ClientResponseError, it allows to inspect response
    content.
    https://doc.scrapinghub.com/autoextract.html#request-level
    """
    def __init__(self, *args, **kwargs):
        self.response_content = kwargs.pop("response_content")
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"RequestError: {self.status}, message={self.message}, " \
               f"headers={self.headers}, body={self.response_content}"


class _QueryError(Exception):
    """ Exception which is raised when a Query-level error is returned.
    https://doc.scrapinghub.com/autoextract.html#query-level
    """

    RETRIABLE_MESSAGES = {
        message.lower().strip()
        for message in [
            "query timed out",
            "Downloader error: No response (network5)",
            "Downloader error: http50",
            "Downloader error: GlobalTimeoutError",
            "Proxy error: banned",
            "Proxy error: internal_error",
            "Proxy error: nxdomain",
            "Proxy error: timeout",
            "Proxy error: ssl_tunnel_error",
            "Proxy error: msgtimeout",
            "Proxy error: econnrefused",
        ]
    }

    def __init__(self, query: dict, message: str, max_retries: int = 0):
        self.query = query
        self.message = message
        self.max_retries = max_retries
        self.domain_occupied = DomainOccupied.from_message(message)

    def __str__(self):
        return f"_QueryError: query={self.query}, message={self.message}, " \
               f"max_retries={self.max_retries}"

    @classmethod
    def from_query_result(cls, query_result: dict, max_retries: int = 0):
        return cls(query=query_result["query"], message=query_result["error"],
                   max_retries=max_retries)

    @property
    def retriable(self) -> bool:
        if self.domain_occupied:
            return True

        return self.message.lower().strip() in self.RETRIABLE_MESSAGES

    @property
    def retry_seconds(self) -> float:
        if self.domain_occupied:
            return self.domain_occupied.retry_seconds

        return 0.0


class QueryRetryError(RetryError):
    """This exception is raised when Tenacity reaches the max retry count or
    timeouts when retrying Query-level errors (see :class:``._QueryError``).
    """
    pass
