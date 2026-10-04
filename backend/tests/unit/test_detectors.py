import pytest

from control_layer.core.detectors import DeterministicSanitizer
from control_layer.core.types import Redaction


def _config():
    return {kind: {"enabled": True} for kind in ("email", "phone", "api_key", "secret")}


def test_sanitizes_all_supported_sensitive_types_without_retaining_values():
    raw = "email jane@example.com phone +48 123 456 789 api sk-abcdefghijklmnop secret password=hunter22"
    result = DeterministicSanitizer(_config()).sanitize(raw)
    assert "jane@example.com" not in result.value
    assert "+48 123 456 789" not in result.value
    assert "sk-abcdefghijklmnop" not in result.value
    assert "hunter22" not in result.value
    assert {item.kind for item in result.redactions} == {"email", "phone", "api_key", "secret"}


def test_sanitization_is_deterministic():
    sanitizer = DeterministicSanitizer(_config())
    value = "a@example.com and a@example.com"
    assert sanitizer.sanitize(value) == sanitizer.sanitize(value)
    assert sanitizer.sanitize(value).value == "[REDACTED_EMAIL_1] and [REDACTED_EMAIL_2]"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("john@example.com.", "[REDACTED_EMAIL_1]."),
        ("john@example.com,", "[REDACTED_EMAIL_1],"),
        ("john@example.com;", "[REDACTED_EMAIL_1];"),
        ("(john@example.com)", "([REDACTED_EMAIL_1])"),
        ("john@example.com!", "[REDACTED_EMAIL_1]!"),
        ("john@example.com?", "[REDACTED_EMAIL_1]?"),
        ("john@example.com...", "[REDACTED_EMAIL_1]..."),
        ("Contact john@example.com", "Contact [REDACTED_EMAIL_1]"),
        ("John.Doe+tag@sub-domain.example.co.uk.", "[REDACTED_EMAIL_1]."),
    ],
)
def test_email_redaction_preserves_surrounding_punctuation(content, expected):
    result = DeterministicSanitizer(_config()).sanitize(content)
    assert result.value == expected
    assert result.redactions == (Redaction("email", 1),)


def test_multiple_emails_in_one_sentence():
    result = DeterministicSanitizer(_config()).sanitize(
        "Ask john@example.com, jane@example.org; or (sam@example.net)."
    )
    assert result.value == "Ask [REDACTED_EMAIL_1], [REDACTED_EMAIL_2]; or ([REDACTED_EMAIL_3])."
    assert result.redactions == (Redaction("email", 3),)


@pytest.mark.parametrize(
    "content",
    [
        "john.example.com",
        "john@localhost",
        "@example.com",
        "john@@example.com",
        ".john@example.com",
        "john..doe@example.com",
        "john.@example.com",
        "john@.example.com",
        "john@example..com",
        "john@-example.com",
        "john@example-.com",
        "john@exam_ple.com",
        "john@example.c",
        "john@example.com123",
        "john@example.com_bad",
        "john@example.com-",
        "john@example.com.invalid-",
        "john@example.com.123",
    ],
)
def test_invalid_email_like_strings_are_not_partially_redacted(content):
    result = DeterministicSanitizer(_config()).sanitize(content)
    assert result.value == content
    assert result.redactions == ()
