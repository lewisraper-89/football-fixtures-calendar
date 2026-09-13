#!/usr/bin/env python3
"""
Football Fixtures Calendar Generator
Fetches football match fixtures from API-Football (v3) for multiple competitions,
aggregates daily match counts, converts times to UK timezone (Europe/London),
and exports an .ics calendar feed with all-day events grouped by date.
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple
import requests
from ics import Calendar, Event

# Configuration
API_FOOTBALL_BASE_URL = "https://api-football-v3.p.rapidapi.com/fixtures"
# API-Football v3 league IDs
COMPETITIONS = {
    42: "League One",
    43: "League Two",
    44: "National League",
    46: "EFL Trophy",
    45: "FA Cup",
    47: "FA Trophy",
}
UK_TIMEZONE = ZoneInfo("Europe/London")
OUTPUT_FILE = "football_fixtures.ics"


def get_api_key() -> str:
    """
    Retrieve API key securely from environment variable.

    Returns:
        str: The API Football key

    Raises:
        ValueError: If API_FOOTBALL_KEY environment variable is not set
    """
    api_key = os.getenv("API_FOOTBALL_KEY")
    if not api_key:
        raise ValueError(
            "API_FOOTBALL_KEY environment variable not set. "
            "Please configure your API key."
        )
    return api_key


def get_season_and_dates() -> Tuple[str, str, str]:
    """
    Determine the current football season and date range for fixtures.
    Football season runs August - June (e.g., 2026 = Aug 2026 - June 2027).

    Returns:
        tuple: (season, from_date, to_date) as strings in format YYYY or YYYY-MM-DD
    """
    today = datetime.now()
    
    if today.month >= 8:
        # August onwards = new season started
        season = str(today.year)
        to_year = today.year + 1
    else:
        # January-July = previous season still running
        season = str(today.year - 1)
        to_year = today.year
    
    from_date = today.strftime("%Y-%m-%d")
    to_date = f"{to_year}-06-01"
    
    return season, from_date, to_date


def fetch_fixtures(league_id: int, season: str, from_date: str, to_date: str, api_key: str) -> List[Dict]:
    """
    Fetch fixtures for a specific league from API-Football.

    Args:
        league_id: The league ID to fetch fixtures for
        season: The season to fetch fixtures for
        from_date: Start date for fixtures (YYYY-MM-DD)
        to_date: End date for fixtures (YYYY-MM-DD)
        api_key: The API Football key

    Returns:
        list: List of fixture dictionaries

    Raises:
        requests.exceptions.RequestException: If API request fails
    """
    headers = {
        "x-rapidapi-host": "api-football-v3.p.rapidapi.com",
        "x-rapidapi-key": api_key,
    }

    params = {
        "league": league_id,
        "season": season,
        "from": from_date,
        "to": to_date,
    }

    try:
        response = requests.get(
            API_FOOTBALL_BASE_URL, headers=headers, params=params, timeout=10
        )
        response.raise_for_status()
        data = response.json()

        if data.get("errors"):
            print(f"API Error for league {league_id}: {data['errors']}", file=sys.stderr)
            return []

        return data.get("response", [])

    except requests.exceptions.RequestException as e:
        print(
            f"Failed to fetch fixtures for league {league_id}: {str(e)}", file=sys.stderr
        )
        return []


def parse_utc_to_uk_time(utc_time_str: str) -> datetime:
    """
    Parse ISO 8601 UTC timestamp and convert to UK local time (Europe/London).

    Args:
        utc_time_str: ISO 8601 formatted timestamp string (e.g., "2026-09-12T15:00:00+00:00")

    Returns:
        datetime: Timezone-aware datetime in Europe/London timezone

    Raises:
        ValueError: If timestamp cannot be parsed
    """
    try:
        # Parse ISO format timestamp
        utc_dt = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))

        # Convert to UK timezone (handles GMT/BST transitions automatically)
        uk_dt = utc_dt.astimezone(UK_TIMEZONE)
        return uk_dt

    except ValueError as e:
        print(f"Failed to parse timestamp '{utc_time_str}': {str(e)}", file=sys.stderr)
        raise


def aggregate_fixtures_by_date(all_fixtures: Dict[int, List[Dict]]) -> Dict[str, Dict]:
    """
    Aggregate fixtures by UK local date, grouping by competition.

    Args:
        all_fixtures: Dictionary mapping league_id to list of fixtures

    Returns:
        dict: Dictionary with keys as dates (YYYY-MM-DD) and values as fixture details
    """
    dates_dict: Dict[str, Dict[int, List[Tuple[str, str, str]]]] = {}

    for league_id, fixtures in all_fixtures.items():
        league_name = COMPETITIONS[league_id]

        for fixture in fixtures:
            # Extract fixture details
            fixture_date = fixture.get("fixture", {}).get("date")
            if not fixture_date:
                continue

            try:
                uk_time = parse_utc_to_uk_time(fixture_date)
                date_key = uk_time.strftime("%Y-%m-%d")

                # Initialize date entry if not exists
                if date_key not in dates_dict:
                    dates_dict[date_key] = {}

                # Initialize league entry if not exists
                if league_id not in dates_dict[date_key]:
                    dates_dict[date_key][league_id] = []

                # Extract match details
                status = fixture.get("fixture", {}).get("status", {}).get("short", "")
                home_team = fixture.get("teams", {}).get("home", {}).get("name", "Unknown")
                away_team = fixture.get("teams", {}).get("away", {}).get("name", "Unknown")
                kickoff_time = uk_time.strftime("%H:%M")

                # Format status prefix if match is postponed or cancelled
                status_prefix = ""
                if status == "PST":
                    status_prefix = "[PST] "
                elif status == "CANC":
                    status_prefix = "[CANC] "

                match_info = (kickoff_time, home_team, away_team, status_prefix)
                dates_dict[date_key][league_id].append(match_info)

            except ValueError:
                continue

    # Convert to final format with sorted matches per competition
    result = {}
    for date_key in sorted(dates_dict.keys()):
        competitions_on_date = {}
        total_matches = 0

        for league_id in sorted(dates_dict[date_key].keys()):
            matches = dates_dict[date_key][league_id]
            # Sort by kickoff time
            matches_sorted = sorted(matches, key=lambda x: x[0])
            competitions_on_date[COMPETITIONS[league_id]] = matches_sorted
            total_matches += len(matches)

        result[date_key] = {"total": total_matches, "competitions": competitions_on_date}

    return result


def format_event_description(competitions_dict: Dict[str, List[Tuple]]) -> str:
    """
    Format event description with competition headers and sorted match times.

    Args:
        competitions_dict: Dictionary mapping competition name to list of matches

    Returns:
        str: Formatted description for calendar event
    """
    lines = []

    for competition_name in sorted(competitions_dict.keys()):
        matches = competitions_dict[competition_name]
        lines.append(f"--- {competition_name} ({len(matches)}) ---")

        for kickoff_time, home_team, away_team, status_prefix in matches:
            lines.append(f"{status_prefix}{kickoff_time} - {home_team} vs {away_team}")

        lines.append("")

    return "\n".join(lines).strip()


def create_calendar_events(
    aggregated_fixtures: Dict[str, Dict],
) -> Calendar:
    """
    Create ICS calendar with all-day events for each date.

    Args:
        aggregated_fixtures: Dictionary of aggregated fixtures by date

    Returns:
        Calendar: ICS Calendar object ready to export
    """
    cal = Calendar()

    for date_str, date_info in sorted(aggregated_fixtures.items()):
        total_matches = date_info["total"]
        competitions_dict = date_info["competitions"]

        # Build competition summary for title
        competition_summary = ", ".join(
            f"{len(matches)} {comp_name}"
            for comp_name, matches in sorted(competitions_dict.items())
        )

        # Create event title
        event_title = f"⚽ Matchday ({total_matches} Games: {competition_summary})"

        # Create event description
        event_description = format_event_description(competitions_dict)

        # Parse date for event
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # Create all-day event
        event = Event()
        event.name = event_title
        event.description = event_description
        event.begin = event_date
        event.duration = timedelta(days=1)
        event.make_all_day()

        cal.events.add(event)

    return cal


def main():
    """
    Main execution function: fetch fixtures, aggregate, and generate calendar.
    """
    try:
        # Retrieve API key
        api_key = get_api_key()

        # Get season and date range
        season, from_date, to_date = get_season_and_dates()
        print(f"Fetching football fixtures for season {season}")
        print(f"  From: {from_date}")
        print(f"  To: {to_date}")

        # Fetch fixtures for all competitions
        all_fixtures = {}
        for league_id, league_name in COMPETITIONS.items():
            print(f"  Fetching {league_name} (ID: {league_id})...")
            fixtures = fetch_fixtures(league_id, season, from_date, to_date, api_key)
            all_fixtures[league_id] = fixtures
            print(f"    Retrieved {len(fixtures)} fixtures")

        # Aggregate fixtures by date
        print("\nAggregating fixtures by UK local date...")
        aggregated = aggregate_fixtures_by_date(all_fixtures)
        print(f"  Found matches on {len(aggregated)} days")

        # Create calendar
        print("\nGenerating ICS calendar...")
        calendar = create_calendar_events(aggregated)

        # Export to file
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.writelines(calendar)

        print(f"\n✅ Calendar exported successfully to '{OUTPUT_FILE}'")
        print(f"   Total events created: {len(calendar.events)}")

    except ValueError as e:
        print(f"❌ Configuration Error: {str(e)}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
