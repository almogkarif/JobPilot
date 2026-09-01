from fastapi.testclient import TestClient

from app.main import _normalize_application_contact_fields, app


def test_application_identity_fields_are_trimmed_deduplicated_and_bounded():
    normalized = _normalize_application_contact_fields({
        "phone_extension": "  12345  ",
        "citizenships": [
            "  Citizen (Israel)  ",
            "citizen (israel)",
            "", None, 123,
            *(f"Citizen ({index})" for index in range(30)),
        ],
    })

    assert normalized["phone_extension"] == "12345"
    assert normalized["citizenships"][0] == "Citizen (Israel)"
    assert len(normalized["citizenships"]) == 20
    assert all(isinstance(value, str) and value == value.strip() for value in normalized["citizenships"])


def test_application_identity_fields_reject_container_values_and_cap_scalar_lengths():
    normalized = _normalize_application_contact_fields({
        "phone_extension": ["123"],
        "citizenships": "Citizen (Israel)",
    })
    assert normalized["phone_extension"] == ""
    assert normalized["citizenships"] == []

    bounded = _normalize_application_contact_fields({
        "phone_extension": "1" * 80,
        "citizenships": ["A" * 200],
    })
    assert bounded["phone_extension"] == "1" * 50
    assert bounded["citizenships"] == ["A" * 160]


def test_profile_patch_persists_identity_fields_without_replacing_other_application_data():
    with TestClient(app) as client:
        before = client.get("/api/profile").json()["application_profile"]
        marker = "preserved-profile-value"
        client.patch("/api/profile", json={"application_profile": {"identity_test_marker": marker}})
        try:
            saved = client.patch("/api/profile", json={"application_profile": {
                "phone_extension": "  321  ",
                "citizenships": [" Citizen (Israel) ", "citizen (israel)"],
            }})
            assert saved.status_code == 200, saved.text
            application_profile = saved.json()["application_profile"]
            assert application_profile["phone_extension"] == "321"
            assert application_profile["citizenships"] == ["Citizen (Israel)"]
            assert application_profile["identity_test_marker"] == marker
        finally:
            client.put("/api/profile", json={
                **client.get("/api/profile").json(),
                "application_profile": before,
            })
