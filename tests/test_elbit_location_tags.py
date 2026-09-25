import asyncio

import pytest

from app.collectors import official


@pytest.mark.parametrize("explicit, description, expected", [
    ("Israel", "Embedded Engineer requirements #Rosh HaAyin", "Rosh HaAyin, Israel"),
    ("", "Work with teams in Haifa #ראש_העין", "Rosh HaAyin, Israel"),
    ("Israel", "Requirements #Beer-Sheva", "Be'er Sheva, Israel"),
    ("Haifa", "Requirements #Rosh HaAyin", "Haifa, Israel"),
    ("USA", "Requirements #Haifa", ""),
    ("Israel", "Experience in C# #Engineering", "Israel"),
    ("Israel", "Requirements #Haifa #Rehovot", "Haifa, Israel; Rehovot, Israel"),
])
def test_elbit_collector_uses_location_tags_as_fallback(monkeypatch, explicit, description, expected):
    async def rows(preset):
        return [{"href": "https://elbitsystemscareer.com/job/?jid=20604",
                 "title": "Embedded Engineer", "location": explicit, "text": description}]

    monkeypatch.setattr(official, "_collect_data_rows", rows)
    jobs = asyncio.run(official.OfficialCareersCollector().collect("elbit"))
    assert jobs[0].location == expected
