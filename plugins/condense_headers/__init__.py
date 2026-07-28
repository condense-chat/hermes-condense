"""Carry per-provider ``extra_headers`` into requests hermes would otherwise
send to the condense proxy unauthenticated.

Two gaps this closes:

1. ``anthropic_messages`` drops ``extra_headers`` entirely.
   ``AIAgent._apply_user_default_headers`` and the
   ``apply_custom_provider_extra_headers_to_client_kwargs`` call above it both
   return early for that api_mode, and
   ``agent.anthropic_adapter.build_anthropic_client`` accepts no
   caller-supplied headers. Result: no ``x-condense-auth-token`` reaches the
   proxy, and the request comes back 401.

2. Auxiliary calls (titles, compaction summaries, vision) build their own
   OpenAI-wire client in ``agent/auxiliary_client.py`` and reach neither the
   ``llm_request`` middleware nor the per-provider headers. They also rewrite
   an ``/anthropic`` base to ``<root>/v1``, which for condense is not a route
   at all, hence ``404 {"detail":"Not Found"}``. Condense's OpenAI surface is
   ``/openai/v1``.

Everything here is additive: non-condense routes are untouched, and every hook
fails open so a bad lookup can never stop a session from starting.
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONDENSE_HEADER_PREFIX = "x-condense-"


def _normalize(url: Optional[str]) -> str:
    """Compare routes the way hermes does: scheme+host+path, no trailing slash."""
    try:
        from hermes_cli.route_identity import normalize_route_base_url

        return normalize_route_base_url(url) or ""
    except Exception:
        return (url or "").strip().rstrip("/").lower()


def _host_of(url: Optional[str]) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def _requested_provider_from_argv() -> str:
    """The ``--provider`` value this process was launched with, if any.

    The middleware context reports ``provider="custom"`` for every named
    ``providers:`` entry (``runtime_provider._resolve_named_custom_runtime``
    hardcodes it), so argv is the only in-process record of which entry the
    user actually selected.
    """
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--provider" and i + 1 < len(argv):
            return argv[i + 1].strip()
        if arg.startswith("--provider="):
            return arg.split("=", 1)[1].strip()
    return ""


def _condense_entries() -> List[Dict[str, Any]]:
    """Configured provider entries that carry ``x-condense-*`` headers."""
    try:
        from hermes_cli.config import get_compatible_custom_providers, load_config

        entries = get_compatible_custom_providers(load_config()) or []
    except Exception:
        logger.debug("condense_headers: config load failed", exc_info=True)
        return []

    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        headers = entry.get("extra_headers") or {}
        if any(str(k).lower().startswith(_CONDENSE_HEADER_PREFIX) for k in headers):
            out.append(entry)
    return out


def _preferred_name() -> str:
    for wanted in (os.environ.get("HERMES_CONDENSE_PROFILE", "").strip(),
                   _requested_provider_from_argv()):
        if wanted:
            return wanted.removeprefix("custom:").lower()
    return ""


def _select_entry(base_url: str, api_mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Pick the entry whose headers apply to a call at *base_url*.

    Exact route match first; several entries can share one condense route and
    differ only by ``x-condense-upstream-url``, so ties fall back to
    ``HERMES_CONDENSE_PROFILE`` then ``--provider``. Auxiliary calls land on a
    rewritten route (``/openai/v1``) that may match no entry. For those, any
    entry on the same condense host supplies the account credentials.
    """
    entries = _condense_entries()
    if not entries:
        return None

    target = _normalize(base_url)
    matches = [e for e in entries if _normalize(e.get("base_url")) == target]
    if api_mode and len(matches) > 1:
        narrowed = [e for e in matches if (e.get("api_mode") or "").strip() == api_mode]
        if narrowed:
            matches = narrowed
    if not matches:
        host = _host_of(base_url)
        matches = [e for e in entries if _host_of(e.get("base_url")) == host] if host else []
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    preferred = _preferred_name()
    if preferred:
        for entry in matches:
            if str(entry.get("name", "")).strip().lower() == preferred:
                return entry

    logger.warning(
        "condense_headers: %d entries match this route and none was selected by "
        "HERMES_CONDENSE_PROFILE or --provider; using %r.",
        len(matches),
        matches[0].get("name"),
    )
    return matches[0]


def _headers_for(base_url: str, api_mode: Optional[str] = None) -> Dict[str, str]:
    entry = _select_entry(base_url, api_mode)
    return dict((entry or {}).get("extra_headers") or {})


# ── 1. main loop: anthropic_messages request kwargs ──────────────────────

def inject_condense_headers(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Merge the selected entry's headers into the provider kwargs.

    ``extra_headers`` is not in ``_RESPONSES_ONLY_KWARGS``, so
    ``sanitize_anthropic_kwargs`` leaves it alone and the SDK applies it
    per request.
    """
    if kwargs.get("api_mode") != "anthropic_messages":
        return None

    request = kwargs.get("request")
    if not isinstance(request, dict):
        return None

    headers = _headers_for(kwargs.get("base_url") or "", "anthropic_messages")
    if not headers:
        return None

    # Merge rather than replace: the fast-mode branch in
    # build_anthropic_kwargs assigns extra_headers wholesale and runs first,
    # so replacing would drop its anthropic-beta value.
    merged = dict(request.get("extra_headers") or {})
    merged.update(headers)

    updated = dict(request)
    updated["extra_headers"] = merged
    return {
        "request": updated,
        "source": "condense_headers",
        # SECURITY: values carry credentials. Name the keys, never the values.
        "reason": f"+{','.join(sorted(headers))}",
    }


# ── 2. every Anthropic client (agent init, credential swap, auxiliary) ───

def _wrap_build_anthropic_client() -> bool:
    """``build_anthropic_client`` is the one chokepoint every Anthropic client
    in the process goes through, including the auxiliary one. ``with_options``
    merges onto the SDK's own headers and preserves base_url / auth / timeout,
    so the adapter's ``anthropic-beta`` and OAuth identity headers survive.
    """
    try:
        from agent import anthropic_adapter
    except Exception:
        logger.debug("condense_headers: anthropic_adapter unavailable", exc_info=True)
        return False

    original = getattr(anthropic_adapter, "build_anthropic_client", None)
    if original is None or getattr(original, "_condense_wrapped", False):
        return False

    def wrapped(api_key, base_url=None, *args, **kwargs):
        client = original(api_key, base_url, *args, **kwargs)
        try:
            headers = _headers_for(base_url or "", "anthropic_messages")
            if headers:
                client = client.with_options(default_headers=headers)
        except Exception:
            logger.warning("condense_headers: header attach failed", exc_info=True)
        return client

    wrapped._condense_wrapped = True
    anthropic_adapter.build_anthropic_client = wrapped
    return True


# ── 3. auxiliary OpenAI-wire path: route rewrite + headers ───────────────

def _wrap_aux_openai() -> bool:
    """Fix the auxiliary client's ``/anthropic`` → OpenAI-wire rewrite for
    condense, and attach the account headers to the client it builds.

    ``_to_openai_base_url`` maps ``<root>/anthropic`` to ``<root>/v1``, which is right
    for MiniMax and DashScope, wrong for condense, whose OpenAI surface is
    ``<root>/openai/v1``. Without this an aux call resolves to
    ``https://<host>/v1/chat/completions``, which matches no condense route and
    returns ``404 {"detail":"Not Found"}``.
    """
    try:
        from agent import auxiliary_client
    except Exception:
        logger.debug("condense_headers: auxiliary_client unavailable", exc_info=True)
        return False

    condense_hosts = {_host_of(e.get("base_url")) for e in _condense_entries()}
    condense_hosts.discard("")

    rewrite = getattr(auxiliary_client, "_to_openai_base_url", None)
    if rewrite is not None and not getattr(rewrite, "_condense_wrapped", False):

        def wrapped_rewrite(base_url: str) -> str:
            url = str(base_url or "").strip().rstrip("/")
            if _host_of(url) in condense_hosts and url.endswith("/anthropic"):
                return url[: -len("/anthropic")] + "/openai/v1"
            return rewrite(base_url)

        wrapped_rewrite._condense_wrapped = True
        auxiliary_client._to_openai_base_url = wrapped_rewrite

    factory = getattr(auxiliary_client, "_create_openai_client", None)
    if factory is not None and not getattr(factory, "_condense_wrapped", False):

        def wrapped_factory(*, api_key: str, base_url: str, **kwargs: Any) -> Any:
            try:
                headers = _headers_for(base_url, "chat_completions")
                if headers:
                    merged = dict(kwargs.get("default_headers") or {})
                    merged.update(headers)
                    kwargs["default_headers"] = merged
            except Exception:
                logger.warning("condense_headers: aux header attach failed", exc_info=True)
            return factory(api_key=api_key, base_url=base_url, **kwargs)

        wrapped_factory._condense_wrapped = True
        auxiliary_client._create_openai_client = wrapped_factory

    return True


def register(ctx) -> None:
    ctx.register_middleware("llm_request", inject_condense_headers)
    _wrap_build_anthropic_client()
    _wrap_aux_openai()
