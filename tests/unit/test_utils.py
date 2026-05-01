"""Unit tests for agents_lib.utils."""
import os
from agents_lib.utils import expand_path, slugify, format_usage_info, sanitize_for_forge


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


class TestSanitizeForForge:
    def test_redacts_env_var_password(self):
        result = sanitize_for_forge("export OS_PASSWORD=supersecret123")
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_redacts_bare_assignment(self):
        result = sanitize_for_forge("GERRIT_HTTP_PASSWORD=abc123abc123abc123abc123")
        assert "abc123abc123abc123abc123" not in result
        assert "[REDACTED]" in result

    def test_redacts_prefixed_cli_flag(self):
        result = sanitize_for_forge("openstack --os-password mypassword token issue")
        assert "mypassword" not in result
        assert "[REDACTED]" in result

    def test_redacts_cli_flag_with_equals(self):
        result = sanitize_for_forge("openstack --os-password=mypassword token issue")
        assert "mypassword" not in result
        assert "[REDACTED]" in result

    def test_redacts_pem_private_key_block(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA...\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = sanitize_for_forge(pem)
        assert "MIIEowIBAAKCAQEA" not in result
        assert "[REDACTED]" in result

    def test_redacts_bearer_token(self):
        result = sanitize_for_forge("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.longtoken")
        assert "eyJhbGciOiJSUzI1NiJ9" not in result
        assert "[REDACTED]" in result

    def test_redacts_basic_auth_header(self):
        result = sanitize_for_forge("Authorization: Basic cmNydWlzZTpzZWNyZXQ=")
        assert "cmNydWlzZTpzZWNyZXQ=" not in result
        assert "[REDACTED]" in result

    def test_redacts_json_password_value(self):
        result = sanitize_for_forge('"password": "hunter2"')
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_redacts_url_credentials(self):
        result = sanitize_for_forge("mysql://admin:p4ssw0rd@localhost/db")
        assert "p4ssw0rd" not in result
        assert "[REDACTED]" in result

    def test_redacts_long_token_after_keyword(self):
        result = sanitize_for_forge("token: abcXYZabcXYZabcXYZabcXYZ")
        assert "abcXYZabcXYZabcXYZabcXYZ" not in result
        assert "[REDACTED]" in result

    def test_preserves_token_usage_prose(self):
        text = "The token usage was 1200 input tokens."
        assert sanitize_for_forge(text) == text

    def test_preserves_openstack_secret_subcommand(self):
        text = "openstack secret store --name my-cert"
        assert sanitize_for_forge(text) == text

    def test_preserves_key_findings_prose(self):
        text = "See the Key Findings section below."
        assert sanitize_for_forge(text) == text

    def test_preserves_plain_https_url(self):
        text = "https://review.opendev.org/c/openstack/octavia/+/985404"
        assert sanitize_for_forge(text) == text

    def test_redacts_home_directory(self):
        home = os.path.expanduser("~")
        text = f"Review saved to {home}/octavia_reviews/review_foo.md"
        result = sanitize_for_forge(text)
        assert home not in result
        assert "~/octavia_reviews/review_foo.md" in result

    def test_already_tilde_path_unchanged(self):
        text = "Review saved to ~/octavia_reviews/review_foo.md"
        assert sanitize_for_forge(text) == text
