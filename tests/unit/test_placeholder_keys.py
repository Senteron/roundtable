"""Provider constructors reject unresolved manifest placeholders.

The Claude Desktop manifest format uses ${user_config.FOO}
substitution to inject install-dialog values into the server's
environment. If a user leaves a key field blank, the substitution
can produce either an empty string OR the literal placeholder
template. Empty strings are caught by the existing truthy-check;
literal placeholders were silently passed to provider SDKs as if
they were real API keys until v0.1.1, producing 401 Unauthorized
at the upstream API and an indistinguishable api_error stub at
the MCP boundary.

These tests pin the v0.1.1 fix: each provider raises a clear
RuntimeError at construction time when the key looks like an
unresolved placeholder, and _resolve_panel() catches the error
and falls back to FakeProvider with a warning.
"""

from __future__ import annotations

import logging

import pytest

from roundtable.providers.base import looks_like_unresolved_placeholder


class TestPlaceholderDetector:
    """Unit tests for the looks_like_unresolved_placeholder helper."""

    def test_empty_string_not_a_placeholder(self) -> None:
        # Empty is caught by the existing truthy-check at the
        # provider level; the detector specifically targets
        # NON-empty placeholder strings.
        assert not looks_like_unresolved_placeholder("")

    def test_real_openai_key_format_passes(self) -> None:
        # OpenAI keys start with "sk-". Not a placeholder.
        assert not looks_like_unresolved_placeholder(
            "sk-proj-AbCdEf1234567890abcdef1234567890"
        )

    def test_real_google_key_format_passes(self) -> None:
        # Google AI Studio keys are 39 chars starting with "AIza".
        assert not looks_like_unresolved_placeholder(
            "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz0123456"
        )

    def test_user_config_placeholder_detected(self) -> None:
        assert looks_like_unresolved_placeholder(
            "${user_config.OPENAI_API_KEY}"
        )
        assert looks_like_unresolved_placeholder(
            "${user_config.GOOGLE_API_KEY}"
        )

    def test_bare_dollar_brace_detected(self) -> None:
        assert looks_like_unresolved_placeholder("${OPENAI_API_KEY}")

    def test_shell_style_dollar_detected_when_user_config_prefix(
        self,
    ) -> None:
        # Some hosts might fall back to shell-style substitution.
        # We catch the user_config prefix variant explicitly.
        assert looks_like_unresolved_placeholder("$user_config.OPENAI_API_KEY")

    def test_leading_whitespace_does_not_hide_placeholder(self) -> None:
        # A trimmed check catches keys that arrived with
        # accidental whitespace from copy-paste or shell expansion.
        assert looks_like_unresolved_placeholder("  ${user_config.OPENAI_API_KEY}")
        assert looks_like_unresolved_placeholder("\n${OPENAI_API_KEY}\n")


class TestProviderConstructorRejectsPlaceholder:
    """Each provider's __init__ must raise RuntimeError on placeholder
    keys, with a message that names the env var and suggests the fix.
    """

    def test_openai_provider_rejects_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "${user_config.OPENAI_API_KEY}")
        from roundtable.providers.openai import OpenAIProvider

        with pytest.raises(RuntimeError) as exc_info:
            OpenAIProvider()
        assert "OPENAI_API_KEY" in str(exc_info.value)
        assert "placeholder" in str(exc_info.value).lower()

    def test_google_provider_rejects_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "${user_config.GOOGLE_API_KEY}")
        from roundtable.providers.google import GoogleProvider

        with pytest.raises(RuntimeError) as exc_info:
            GoogleProvider()
        assert "GOOGLE_API_KEY" in str(exc_info.value)
        assert "placeholder" in str(exc_info.value).lower()

    def test_deepseek_provider_rejects_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "${user_config.DEEPSEEK_API_KEY}")
        from roundtable.providers.deepseek import DeepSeekProvider

        with pytest.raises(RuntimeError) as exc_info:
            DeepSeekProvider()
        assert "DEEPSEEK_API_KEY" in str(exc_info.value)
        assert "placeholder" in str(exc_info.value).lower()


class TestResolvePanelHandlesPlaceholder:
    """The MCP server's _resolve_panel catches provider construction
    failures and falls back to FakeProvider with a warning. Verify
    the v0.1.0 bug — placeholder key reaching the SDK as if it were
    real — cannot recur.
    """

    def test_resolve_panel_falls_back_with_warning_on_placeholder(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from roundtable.mcp_server import _resolve_panel
        from roundtable.providers.fake import FakeProvider

        monkeypatch.setenv("OPENAI_API_KEY", "${user_config.OPENAI_API_KEY}")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        caplog.set_level(logging.WARNING, logger="roundtable.mcp_server")

        panel = _resolve_panel(["gpt-4o"])

        assert len(panel) == 1
        assert isinstance(panel[0], FakeProvider), (
            "placeholder key must not reach the real SDK; expected "
            "FakeProvider fallback"
        )
        assert panel[0].name == "gpt-4o"
        # The warning should mention the placeholder so an operator
        # reading stderr can act on it.
        assert "placeholder" in caplog.text.lower()
