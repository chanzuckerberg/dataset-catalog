import httpx


class BaseClient:

    prefix: str = ""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http


class AsyncBaseClient:

    prefix: str = ""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
