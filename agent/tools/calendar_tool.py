"""
Calendar Tool — manage Google Calendar events.

How Google Calendar API works:
- It's a REST API: you send HTTP requests to Google's servers
- The google-api-python-client library wraps these requests nicely
- Authentication uses OAuth2 tokens (see scripts/setup_google_oauth.py)

Key concepts:
- CALENDAR ID: "primary" means your main calendar. You can also use
  specific calendar IDs for shared or secondary calendars.
- RFC 3339: Date format Google uses, e.g. "2024-01-15T10:00:00-05:00"
  (ISO 8601 with timezone offset). Python's datetime.isoformat() produces this.
- TIME ZONE: Events need a timezone. We default to the system's local timezone.
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from agent.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_local_timezone() -> str:
    """Get the system's local timezone name (e.g., 'America/New_York')."""
    try:
        # On macOS/Linux, this reads /etc/localtime
        local_tz = datetime.now().astimezone().tzinfo
        tz_name = str(local_tz)
        # If it's a valid IANA name, use it; otherwise default to UTC
        ZoneInfo(tz_name)
        return tz_name
    except Exception:
        return "UTC"


def _format_event(event: dict) -> dict:
    """Format a Google Calendar event into a clean dict for the LLM."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Events can be all-day (date) or timed (dateTime)
    start_str = start.get("dateTime", start.get("date", "unknown"))
    end_str = end.get("dateTime", end.get("date", "unknown"))

    return {
        "id": event.get("id", ""),
        "summary": event.get("summary", "(no title)"),
        "start": start_str,
        "end": end_str,
        "location": event.get("location", ""),
        "description": (event.get("description", "") or "")[:200],
        "status": event.get("status", ""),
        "organizer": event.get("organizer", {}).get("email", ""),
    }


class CalendarTool(Tool):
    """
    Google Calendar tool — list, create, update, and delete events.

    Requires OAuth2 setup: run `python scripts/setup_google_oauth.py` first.
    The token is cached in data/google_token.json and auto-refreshes.
    """

    def __init__(self, credentials_path: str, token_path: str):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None
        self._timezone = _get_local_timezone()

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return (
            "Manage Google Calendar. Actions: "
            "list_events (show upcoming events), "
            "create_event (schedule a new event), "
            "update_event (modify an existing event), "
            "delete_event (remove an event), "
            "find_free_time (find available slots)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action", "string",
                "The calendar action to perform",
                enum=["list_events", "create_event", "update_event", "delete_event", "find_free_time"],
            ),
            ToolParameter(
                "days", "integer",
                "Number of days ahead to look (default: 7) — used with list_events and find_free_time",
                required=False,
            ),
            ToolParameter(
                "summary", "string",
                "Event title — used with create_event and update_event",
                required=False,
            ),
            ToolParameter(
                "start_time", "string",
                "Start time in ISO format like '2024-01-15T10:00:00' — used with create_event and update_event",
                required=False,
            ),
            ToolParameter(
                "end_time", "string",
                "End time in ISO format like '2024-01-15T11:00:00' — used with create_event (defaults to 1 hour after start)",
                required=False,
            ),
            ToolParameter(
                "location", "string",
                "Event location — used with create_event and update_event",
                required=False,
            ),
            ToolParameter(
                "event_description", "string",
                "Event description/notes — used with create_event and update_event",
                required=False,
            ),
            ToolParameter(
                "event_id", "string",
                "Event ID — used with update_event and delete_event",
                required=False,
            ),
        ]

    # ── Authentication ─────────────────────────────────────────────

    def _get_service(self):
        """
        Get an authenticated Google Calendar API service.

        This handles the token lifecycle:
        1. Load saved token from disk
        2. If expired, refresh it using the refresh token
        3. Save the new token back to disk
        4. Build and return the API service object
        """
        if self._service is not None:
            return self._service

        if not os.path.exists(self._token_path):
            raise FileNotFoundError(
                "Google Calendar not authenticated. "
                "Run: python scripts/setup_google_oauth.py"
            )

        creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)

        # Refresh expired token automatically
        if creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google Calendar token...")
            creds.refresh(Request())
            with open(self._token_path, "w") as f:
                f.write(creds.to_json())

        if not creds.valid:
            raise ValueError(
                "Google Calendar token is invalid. "
                "Run: python scripts/setup_google_oauth.py"
            )

        # Build the Calendar API service
        # This creates a Python object with methods like .events().list(), .events().insert(), etc.
        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    # ── Main Execute ───────────────────────────────────────────────

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            service = self._get_service()

            if action == "list_events":
                return await self._list_events(service, days=kwargs.get("days", 7))

            elif action == "create_event":
                summary = kwargs.get("summary", "")
                start_time = kwargs.get("start_time", "")
                if not summary or not start_time:
                    return ToolResult(success=False, data=None, error="'summary' and 'start_time' are required to create an event")
                return await self._create_event(
                    service,
                    summary=summary,
                    start_time=start_time,
                    end_time=kwargs.get("end_time"),
                    location=kwargs.get("location"),
                    description=kwargs.get("event_description"),
                )

            elif action == "update_event":
                event_id = kwargs.get("event_id", "")
                if not event_id:
                    return ToolResult(success=False, data=None, error="'event_id' is required to update an event")
                return await self._update_event(service, event_id=event_id, **kwargs)

            elif action == "delete_event":
                event_id = kwargs.get("event_id", "")
                if not event_id:
                    return ToolResult(success=False, data=None, error="'event_id' is required to delete an event")
                return await self._delete_event(service, event_id=event_id)

            elif action == "find_free_time":
                return await self._find_free_time(service, days=kwargs.get("days", 7))

            else:
                return ToolResult(success=False, data=None, error=f"Unknown action: {action}")

        except FileNotFoundError as e:
            return ToolResult(success=False, data=None, error=str(e))
        except Exception as e:
            logger.exception("Calendar tool error")
            return ToolResult(success=False, data=None, error=f"Calendar error: {e}")

    # ── Actions ────────────────────────────────────────────────────

    async def _list_events(self, service, days: int = 7) -> ToolResult:
        """List upcoming events for the next N days."""
        now = datetime.now(ZoneInfo(self._timezone))
        end = now + timedelta(days=days)

        # The Calendar API uses RFC 3339 timestamps
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,          # Expand recurring events
            orderBy="startTime",
            maxResults=20,
        ).execute()

        events = events_result.get("items", [])

        if not events:
            return ToolResult(
                success=True,
                data={"events": [], "message": f"No events in the next {days} days."},
            )

        formatted = [_format_event(e) for e in events]
        return ToolResult(
            success=True,
            data={
                "count": len(formatted),
                "period": f"Next {days} days",
                "timezone": self._timezone,
                "events": formatted,
            },
        )

    async def _create_event(self, service, summary: str, start_time: str,
                            end_time: str = None, location: str = None,
                            description: str = None) -> ToolResult:
        """Create a new calendar event."""
        # Parse the start time
        start_dt = datetime.fromisoformat(start_time)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=ZoneInfo(self._timezone))

        # Default end time: 1 hour after start
        if end_time:
            end_dt = datetime.fromisoformat(end_time)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=ZoneInfo(self._timezone))
        else:
            end_dt = start_dt + timedelta(hours=1)

        event_body = {
            "summary": summary,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": self._timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": self._timezone},
        }

        if location:
            event_body["location"] = location
        if description:
            event_body["description"] = description

        created = service.events().insert(calendarId="primary", body=event_body).execute()

        logger.info(f"Created event: {summary} at {start_time}")
        return ToolResult(
            success=True,
            data={
                "message": f"Event '{summary}' created successfully",
                "event": _format_event(created),
                "link": created.get("htmlLink", ""),
            },
        )

    async def _update_event(self, service, event_id: str, **kwargs) -> ToolResult:
        """Update an existing calendar event."""
        # Fetch the current event
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        # Update only the fields that were provided
        if kwargs.get("summary"):
            event["summary"] = kwargs["summary"]
        if kwargs.get("location"):
            event["location"] = kwargs["location"]
        if kwargs.get("event_description"):
            event["description"] = kwargs["event_description"]
        if kwargs.get("start_time"):
            start_dt = datetime.fromisoformat(kwargs["start_time"])
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=ZoneInfo(self._timezone))
            event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": self._timezone}
        if kwargs.get("end_time"):
            end_dt = datetime.fromisoformat(kwargs["end_time"])
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=ZoneInfo(self._timezone))
            event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": self._timezone}

        updated = service.events().update(
            calendarId="primary", eventId=event_id, body=event,
        ).execute()

        logger.info(f"Updated event: {event_id}")
        return ToolResult(
            success=True,
            data={
                "message": "Event updated successfully",
                "event": _format_event(updated),
            },
        )

    async def _delete_event(self, service, event_id: str) -> ToolResult:
        """Delete a calendar event."""
        # Fetch event first to show what was deleted
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        summary = event.get("summary", "(no title)")

        service.events().delete(calendarId="primary", eventId=event_id).execute()

        logger.info(f"Deleted event: {event_id} ({summary})")
        return ToolResult(
            success=True,
            data={"message": f"Event '{summary}' deleted successfully"},
        )

    async def _find_free_time(self, service, days: int = 7) -> ToolResult:
        """
        Find free time slots in the next N days.

        Strategy: fetch all events, then find gaps between them
        during working hours (9 AM - 6 PM).
        """
        now = datetime.now(ZoneInfo(self._timezone))
        end = now + timedelta(days=days)

        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])

        # Build list of busy periods
        busy = []
        for event in events:
            start = event.get("start", {})
            end_e = event.get("end", {})
            start_str = start.get("dateTime")
            end_str = end_e.get("dateTime")
            if start_str and end_str:
                busy.append((
                    datetime.fromisoformat(start_str),
                    datetime.fromisoformat(end_str),
                ))

        # Find free slots during working hours (9 AM - 6 PM)
        free_slots = []
        tz = ZoneInfo(self._timezone)

        for day_offset in range(days):
            day = now.date() + timedelta(days=day_offset)
            work_start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=tz)
            work_end = datetime(day.year, day.month, day.day, 18, 0, tzinfo=tz)

            # Skip if work_start is in the past
            if work_start < now:
                work_start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                if work_start >= work_end:
                    continue

            # Find gaps in this day's working hours
            current = work_start
            for busy_start, busy_end in sorted(busy):
                if busy_end <= current:
                    continue
                if busy_start >= work_end:
                    break
                if busy_start > current:
                    free_slots.append({
                        "date": day.isoformat(),
                        "start": current.strftime("%H:%M"),
                        "end": min(busy_start, work_end).strftime("%H:%M"),
                        "duration_minutes": int((min(busy_start, work_end) - current).total_seconds() / 60),
                    })
                current = max(current, busy_end)

            if current < work_end:
                free_slots.append({
                    "date": day.isoformat(),
                    "start": current.strftime("%H:%M"),
                    "end": work_end.strftime("%H:%M"),
                    "duration_minutes": int((work_end - current).total_seconds() / 60),
                })

        return ToolResult(
            success=True,
            data={
                "period": f"Next {days} days",
                "working_hours": "9:00 AM - 6:00 PM",
                "timezone": self._timezone,
                "free_slot_count": len(free_slots),
                "free_slots": free_slots[:15],  # Limit to save context
            },
        )
