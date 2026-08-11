from agent.fields import known_value


def test_saved_application_password_fills_password_and_confirmation_fields():
    profile = {"full_name": "Demo Candidate", "application_password": "Example-only-password-123!"}
    password = known_value("Password*", "password", profile, {}, [])
    confirmation = known_value("Confirm Password*", "password", profile, {}, [])
    assert password and password.value == "Example-only-password-123!"
    assert confirmation and confirmation.value == "Example-only-password-123!"
