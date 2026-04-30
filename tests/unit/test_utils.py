"""Unit tests for agents_lib.utils."""
from agents_lib.utils import expand_path, slugify, format_usage_info


class TestSlugify:
    def test_basic_spaces(self):
        assert slugify("hello world") == "hello_world"

    def test_lowercase(self):
        assert slugify("Hello World") == "hello_world"

    def test_special_chars_stripped(self):
        result = slugify("Bug #123: Fails!")
        assert "#" not in result
        assert "!" not in result
        assert ":" not in result

    def test_max_length_truncation(self):
        long_text = "a" * 100
        result = slugify(long_text, max_length=20)
        assert len(result) <= 20

    def test_max_length_no_trailing_underscore(self):
        # Truncation should not leave trailing underscores
        result = slugify("word another_word x", max_length=10)
        assert not result.endswith("_")

    def test_empty_string(self):
        assert slugify("") == ""

    def test_only_special_chars(self):
        result = slugify("!@#$%")
        assert result == ""

    def test_numbers_preserved(self):
        assert "123" in slugify("bug 123")

    def test_default_max_length(self):
        long_text = "a very long title that exceeds fifty characters in total length here"
        result = slugify(long_text)
        assert len(result) <= 50

    def test_consecutive_specials_collapsed(self):
        result = slugify("hello---world")
        assert "___" not in result


class TestExpandPath:
    def test_tilde_expansion(self):
        result = expand_path("~/foo/bar")
        assert not result.startswith("~")
        assert result.endswith("foo/bar")

    def test_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("MY_DIR", "/some/path")
        result = expand_path("$MY_DIR/sub")
        assert result == "/some/path/sub"

    def test_absolute_path_unchanged(self):
        assert expand_path("/absolute/path") == "/absolute/path"

    def test_none_returns_none(self):
        assert expand_path(None) is None

    def test_empty_string_returns_empty(self):
        assert expand_path("") == ""


class TestFormatUsageInfo:
    def test_full_info(self):
        usage = {"input_tokens": 1000, "output_tokens": 200}
        result = format_usage_info(usage_data=usage, cost_usd=0.005, model="claude-sonnet-4-6", duration_ms=3000)
        assert "1,000" in result
        assert "200" in result
        assert "0.005" in result
        assert "claude-sonnet-4-6" in result
        assert "3.00s" in result

    def test_no_cost(self):
        usage = {"input_tokens": 500, "output_tokens": 100}
        result = format_usage_info(usage_data=usage, cost_usd=None)
        assert "500" in result
        assert "$" not in result

    def test_all_none(self):
        result = format_usage_info()
        assert result  # Returns "not available" string, not empty

    def test_cache_tokens_shown_when_nonzero(self):
        usage = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_input_tokens": 50,
            "cache_read_input_tokens": 300,
        }
        result = format_usage_info(usage_data=usage)
        assert "Cache" in result

    def test_cache_tokens_hidden_when_zero(self):
        usage = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        result = format_usage_info(usage_data=usage)
        assert "cache creation" not in result.lower()
