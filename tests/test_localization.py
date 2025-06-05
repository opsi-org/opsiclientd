from unittest import mock

from opsiclientd.Localization import _


def mocked_translation(input: str) -> str:
	# Mocked translation function for testing
	return "Dies ist ein Test mit %s, %.2f und %d"


def test_localization():
	# Test that the translation function is callable
	assert callable(_), "Translation function should be callable"

	# Test that the translation function returns a string
	result = _("Test message")
	assert isinstance(result, str), "Translation should return a string"

	original_message = "This is a test with %s, %.2f and %d"
	assert _(original_message) == original_message  # no translation function

	with mock.patch("opsiclientd.Localization.translation_func", mocked_translation):
		original_message = "This is a test with %s, %.2f and %d"
		assert _(original_message) == "Dies ist ein Test mit %s, %.2f und %d"

		original_message = "This is a test with %.2f, %s and %d"
		assert _(original_message) == original_message  # wrong placeholders
