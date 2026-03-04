"""
Unit tests for message formatting helpers — P4-7.

Acceptance criteria covered:
- TC-P4-7.1: format_help() contains /draft description.
- TC-P4-7.2: format_help() updated /analyze description — photo can be sent without command.
- TC-P4-7.3: format_start() does not contain instruction to use /analyze with photo.
- TC-P4-7.4: format_start() mentions smart photo routing (photo without command).
- TC-P4-7.7: format_help() contains the word "draft".
- TC-P4-7.8: format_start() mentions ability to send photo without command.
"""

from src.bot.messages import format_help, format_start


def test_format_help_contains_draft():
    """TC-P4-7.1 / TC-P4-7.7: format_help() mentions /draft command."""
    text = format_help()
    assert "draft" in text.lower()
    assert "/draft" in text


def test_format_help_analyze_no_command_required():
    """TC-P4-7.2: format_help() indicates photo can be sent without /analyze."""
    text = format_help()
    # Should mention that photo can be sent without the command
    assert "без" in text or "автоматично" in text


def test_format_start_no_mandatory_analyze():
    """TC-P4-7.3: format_start() does not instruct user to use /analyze with photo."""
    text = format_start()
    # Old instruction was "Надішліть фото вашої колоди разом з командою /analyze"
    assert "разом з командою /analyze" not in text


def test_format_start_mentions_photo_routing():
    """TC-P4-7.4 / TC-P4-7.8: format_start() mentions automatic photo routing."""
    text = format_start()
    # Should mention automatic detection when photo is sent without command
    assert "автоматично" in text
