"""JIRA integration service - mock mode when no URL configured, real mode via httpx."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import httpx
import structlog

logger = structlog.get_logger(__name__)


class JiraService:
    def __init__(self, base_url: str | None = None, email: str | None = None, api_token: str | None = None, project_key: str = "COST"):
        self._base_url = base_url
        self._email = email
        self._api_token = api_token
        self._project_key = project_key
        self._mock = not base_url
        self._mock_tickets: dict[str, dict] = {}

    @property
    def is_mock(self) -> bool:
        return self._mock

    async def create_ticket(
        self,
        summary: str,
        description: str,
        priority: str = "Medium",
        labels: list[str] | None = None,
        recommendation_id: int | None = None,
    ) -> dict:
        if self._mock:
            ticket_key = f"{self._project_key}-{len(self._mock_tickets) + 1}"
            ticket = {
                "key": ticket_key,
                "url": f"https://mock-jira.example.com/browse/{ticket_key}",
                "summary": summary,
                "description": description,
                "priority": priority,
                "status": "To Do",
                "labels": labels or ["cost-optimization"],
                "recommendation_id": recommendation_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._mock_tickets[ticket_key] = ticket
            logger.info("jira_mock_ticket_created", key=ticket_key)
            return ticket

        auth = httpx.BasicAuth(self._email, self._api_token)
        payload = {
            "fields": {
                "project": {"key": self._project_key},
                "summary": summary,
                "description": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": description}]}
                ]},
                "issuetype": {"name": "Task"},
                "priority": {"name": priority},
                "labels": labels or ["cost-optimization"],
            }
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/rest/api/3/issue",
                json=payload,
                auth=auth,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "key": data["key"],
                "url": f"{self._base_url}/browse/{data['key']}",
                "summary": summary,
                "status": "To Do",
            }

    async def get_ticket(self, ticket_key: str) -> dict | None:
        if self._mock:
            return self._mock_tickets.get(ticket_key)

        auth = httpx.BasicAuth(self._email, self._api_token)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base_url}/rest/api/3/issue/{ticket_key}",
                auth=auth,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return {
                "key": data["key"],
                "url": f"{self._base_url}/browse/{data['key']}",
                "summary": data["fields"]["summary"],
                "status": data["fields"]["status"]["name"],
            }

    async def get_tickets_for_recommendation(self, recommendation_id: int) -> list[dict]:
        if self._mock:
            return [t for t in self._mock_tickets.values() if t.get("recommendation_id") == recommendation_id]
        return []
