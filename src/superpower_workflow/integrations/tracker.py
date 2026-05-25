from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from typing import Any, Protocol


class TrackerAdapter(Protocol):
    def fetch_ticket(self, ticket_id: str) -> dict[str, Any]: ...
    def update_status(self, ticket_id: str, status: str, comment: str = "") -> bool: ...
    def ticket_to_milestone(self, ticket_data: dict[str, Any]) -> dict[str, Any]: ...


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50]


class LinearAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self._api_url = config.get("api_url", "https://api.linear.app/graphql")
        self._token_env = config.get("token_env", "LINEAR_API_TOKEN")

    def _get_token(self) -> str:
        token = os.environ.get(self._token_env, "")
        if not token:
            raise ValueError(f"Missing token: env var '{self._token_env}' not set")
        return token

    def fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        token = self._get_token()
        query = {
            "query": (
                "query($id: String!) { issue(id: $id) { id title description "
                "priority { label } assignee { name } state { name } } }"
            ),
            "variables": {"id": ticket_id},
        }
        req = urllib.request.Request(
            self._api_url,
            data=json.dumps(query).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": token,
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        issue = data.get("data", {}).get("issue", {})
        return {
            "id": issue.get("id", ""),
            "title": issue.get("title", ""),
            "description": issue.get("description", ""),
            "priority": issue.get("priority", {}).get("label", ""),
            "assignee": (
                issue.get("assignee", {}).get("name", "") if issue.get("assignee") else ""
            ),
            "status": issue.get("state", {}).get("name", ""),
        }

    def _lookup_state_id(self, name: str) -> str | None:
        token = self._get_token()
        query = {
            "query": (
                "query($name: String!) { workflowStates(filter: {name: {eq: $name}}) "
                "{ nodes { id } } }"
            ),
            "variables": {"name": name},
        }
        req = urllib.request.Request(
            self._api_url,
            data=json.dumps(query).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": token},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            nodes = data.get("data", {}).get("workflowStates", {}).get("nodes", [])
            return nodes[0]["id"] if nodes else None
        except (OSError, IndexError, KeyError):
            return None

    def update_status(self, ticket_id: str, status: str, comment: str = "") -> bool:
        token = self._get_token()
        state_id = self._lookup_state_id(status) if not status.startswith("state-") else status
        if not state_id:
            return False
        mutation = {
            "query": (
                "mutation($id: String!, $stateId: String!) { "
                "issueUpdate(id: $id, input: { stateId: $stateId }) { success } }"
            ),
            "variables": {"id": ticket_id, "stateId": state_id},
        }
        req = urllib.request.Request(
            self._api_url,
            data=json.dumps(mutation).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": token,
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            return data.get("data", {}).get("issueUpdate", {}).get("success", False)
        except OSError:
            return False

    def ticket_to_milestone(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": _slugify(ticket_data.get("title", "untitled")),
            "description": ticket_data.get("title", ""),
            "spec_sections": ticket_data.get("description", ""),
            "depends_on": [],
        }


class JiraAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self._api_url = config.get("api_url", "").rstrip("/")
        self._token_env = config.get("token_env", "JIRA_API_TOKEN")
        self._user_env = config.get("user_env", "JIRA_USER_EMAIL")

    def _auth_header(self) -> str:
        token = os.environ.get(self._token_env, "")
        user = os.environ.get(self._user_env, "")
        if not token:
            raise ValueError(f"Missing token: env var '{self._token_env}' not set")
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        return f"Basic {creds}"

    def fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        auth = self._auth_header()
        url = f"{self._api_url}/rest/api/3/issue/{ticket_id}"
        req = urllib.request.Request(
            url, headers={"Authorization": auth, "Accept": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        fields = data.get("fields", {})
        return {
            "id": data.get("key", ""),
            "title": fields.get("summary", ""),
            "description": fields.get("description", ""),
            "priority": (
                fields.get("priority", {}).get("name", "") if fields.get("priority") else ""
            ),
            "assignee": (
                fields.get("assignee", {}).get("displayName", "") if fields.get("assignee") else ""
            ),
            "status": fields.get("status", {}).get("name", "") if fields.get("status") else "",
        }

    def update_status(self, ticket_id: str, status: str, comment: str = "") -> bool:
        auth = self._auth_header()
        try:
            trans_url = f"{self._api_url}/rest/api/3/issue/{ticket_id}/transitions"
            req = urllib.request.Request(
                trans_url,
                headers={"Authorization": auth, "Accept": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=15)
            transitions = json.loads(resp.read()).get("transitions", [])
            target = next(
                (t for t in transitions if t.get("name", "").lower() == status.lower()),
                None,
            )
            if target:
                body = json.dumps({"transition": {"id": target["id"]}}).encode()
                req = urllib.request.Request(
                    trans_url,
                    data=body,
                    method="POST",
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=15)
        except OSError:
            pass
        if comment:
            url = f"{self._api_url}/rest/api/3/issue/{ticket_id}/comment"
            body = json.dumps(
                {
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": comment}],
                            }
                        ],
                    }
                }
            ).encode()
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={"Authorization": auth, "Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=15)
            except OSError:
                return False
        return True

    def ticket_to_milestone(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": _slugify(ticket_data.get("title", "untitled")),
            "description": ticket_data.get("title", ""),
            "spec_sections": ticket_data.get("description", ""),
            "depends_on": [],
        }


def create_tracker(config: dict[str, Any]) -> TrackerAdapter | None:
    tracker_config = config.get("integrations", {}).get("tracker")
    if not tracker_config:
        return None
    tracker_type = tracker_config.get("type", "")
    if tracker_type == "linear":
        return LinearAdapter(tracker_config)
    if tracker_type == "jira":
        return JiraAdapter(tracker_config)
    return None
