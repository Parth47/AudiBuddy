"""Supabase client using httpx (REST API directly).

Uses a persistent httpx.AsyncClient for connection pooling and keep-alive,
which dramatically reduces latency compared to creating a new client per request.
"""

import asyncio
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class SupabaseClient:
    """Lightweight Supabase client using REST API with persistent connection pool."""

    def __init__(self):
        self.url = settings.SUPABASE_URL
        self.rest_url = f"{self.url}/rest/v1"
        self.storage_url = f"{self.url}/storage/v1"
        self.headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        # Persistent client — reuses TCP connections (keep-alive) across requests
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create a persistent httpx client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=30,
                ),
            )
        return self._client

    async def close(self):
        """Close the persistent client. Call on app shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: dict | list[dict] | None = None,
        content: bytes | None = None,
        timeout: float = 30.0,
    ) -> list[dict] | dict:
        last_error: Exception | None = None

        for attempt in range(1, settings.SUPABASE_REQUEST_MAX_RETRIES + 1):
            try:
                if headers and headers != self.headers:
                    # Use a one-off client for requests with custom headers (e.g. file uploads)
                    async with httpx.AsyncClient(headers=headers, timeout=timeout) as temp_client:
                        response = await temp_client.request(
                            method,
                            url,
                            params=params,
                            json=json,
                            content=content,
                        )
                else:
                    client = await self._get_client()
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json,
                        content=content,
                        extensions={"timeout": {"read": timeout, "write": timeout, "connect": 10.0, "pool": 10.0}},
                    )

                if (
                    response.status_code in RETRYABLE_STATUS_CODES
                    and attempt < settings.SUPABASE_REQUEST_MAX_RETRIES
                ):
                    await asyncio.sleep(min(2 ** (attempt - 1), 5))
                    continue

                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.RequestError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in RETRYABLE_STATUS_CODES
                )
                last_error = exc

                if not retryable or attempt == settings.SUPABASE_REQUEST_MAX_RETRIES:
                    raise

                await asyncio.sleep(min(2 ** (attempt - 1), 5))

        if last_error:
            raise last_error
        raise RuntimeError("Supabase request failed without an error")

    # ---- Database Operations ----

    async def select(self, table: str, query_params: dict | None = None) -> list[dict]:
        """SELECT rows from a table. query_params are appended as URL params."""
        response = await self._request_json(
            "GET",
            f"{self.rest_url}/{table}",
            params=query_params or {},
        )
        return self._as_rows(response)

    async def insert(self, table: str, data: dict | list[dict]) -> list[dict]:
        """INSERT one or more rows into a table."""
        response = await self._request_json(
            "POST",
            f"{self.rest_url}/{table}",
            json=data,
        )
        return self._as_rows(response)

    async def update(self, table: str, data: dict, match: dict) -> list[dict]:
        """UPDATE rows matching the given filters."""
        params = {f"{key}": f"eq.{value}" for key, value in match.items()}
        response = await self._request_json(
            "PATCH",
            f"{self.rest_url}/{table}",
            params=params,
            json=data,
        )
        return self._as_rows(response)

    async def delete(self, table: str, match: dict) -> list[dict]:
        """DELETE rows matching the given filters."""
        params = {f"{key}": f"eq.{value}" for key, value in match.items()}
        response = await self._request_json(
            "DELETE",
            f"{self.rest_url}/{table}",
            params=params,
        )
        return self._as_rows(response)

    # ---- Storage Operations ----

    async def upload_file(
        self,
        bucket: str,
        path: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict:
        """Upload a file to Supabase Storage (with upsert to handle re-uploads)."""
        response = await self._request_json(
            "POST",
            f"{self.storage_url}/object/{bucket}/{path}",
            headers={
                **self.headers,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=file_data,
            timeout=120.0,
        )
        return response if isinstance(response, dict) else response[0]

    async def delete_file(self, bucket: str, path: str, *, ignore_missing: bool = True) -> list[dict]:
        """Delete a file from Supabase Storage."""
        return await self.delete_files(bucket, [path], ignore_missing=ignore_missing)

    async def delete_files(
        self,
        bucket: str,
        paths: list[str],
        *,
        ignore_missing: bool = True,
    ) -> list[dict]:
        """Delete one or more files from Supabase Storage."""
        normalized_paths = [path.strip("/") for path in paths if path]
        if not normalized_paths:
            return []

        try:
            response = await self._request_json(
                "DELETE",
                f"{self.storage_url}/object/{bucket}",
                json={"prefixes": normalized_paths},
            )
        except httpx.HTTPStatusError as exc:
            if ignore_missing and exc.response.status_code in {400, 404}:
                return []
            raise
        return self._as_rows(response)

    async def download_file(self, bucket: str, path: str) -> bytes:
        """Download a file from Supabase Storage and return its bytes."""
        client = await self._get_client()
        url = f"{self.storage_url}/object/{bucket}/{path}"
        response = await client.get(url)
        response.raise_for_status()
        return response.content

    def get_public_url(self, bucket: str, path: str) -> str:
        """Get the public URL for a file in a public bucket."""
        return f"{self.storage_url}/object/public/{bucket}/{path}"

    @staticmethod
    def _as_rows(response: list[dict] | dict) -> list[dict]:
        if response == {}:
            return []
        return response if isinstance(response, list) else [response]


# Singleton instance
db = SupabaseClient()
