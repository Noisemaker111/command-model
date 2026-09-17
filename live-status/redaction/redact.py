"""Secret redaction applied before any command leaves the private store.

Patterns favour recall over precision: a redacted non-secret costs one placeholder,
a missed secret leaks. `redact()` is idempotent and `find_secrets()` powers the
leak validators used on model outputs.
"""
from __future__ import annotations

import math
import re

# (placeholder, pattern). Order matters: specific vendor formats before generic ones.
_VENDOR = [
    ("<PRIVATE_KEY>", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)"),
    ("<API_KEY>", r"\bsk-(?:ant-|proj-|or-v1-|live-|test-)?[A-Za-z0-9_\-]{16,}"),
    ("<API_KEY>", r"\b(?:rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    ("<TOKEN>", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("<TOKEN>", r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("<TOKEN>", r"\bglpat-[A-Za-z0-9_\-]{20,}"),
    ("<TOKEN>", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    ("<API_KEY>", r"\bAKIA[0-9A-Z]{16}\b"),
    ("<API_KEY>", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("<TOKEN>", r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    ("<TOKEN>", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("<TOKEN>", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("<API_KEY>", r"\bgsk_[A-Za-z0-9]{40,}\b"),
    ("<API_KEY>", r"\bxai-[A-Za-z0-9]{40,}\b"),
    ("<TOKEN>", r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    ("<SECRET>", r"\bvc[pkr]_[A-Za-z0-9]{20,}\b"),
    ("<SECRET>", r"\bsk_[A-Za-z0-9]{32,}\b"),
]

# Credential-ish names. `(?-i:(?![a-z]))` stops plurals and longer words (tokens, passwordless).
_KEYWORDS = (r"(?:api[_-]?key|apikey|access[_-]?key|secret(?:[_-]?key)?|client[_-]?secret|"
             r"token|access[_-]?token|refresh[_-]?token|auth[_-]?token|bearer|passw(?:or)?d|pwd|"
             r"passphrase|private[_-]?key|credentials?)(?-i:(?![a-z]))")

_CONTEXT = [
    # Authorization / cookie headers in curl, Invoke-WebRequest hashtables, etc.
    ("<TOKEN>", r"(?i)(\bauthorization\b\s*[:=]\s*[\"']?\s*(?:bearer|basic|token|bot)\s+)([^\s\"',;}]+)"),
    ("<TOKEN>", r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/\-]{12,}=*)"),
    ("<COOKIE>", r"(?i)(\b(?:set-)?cookie\b\s*[:=]\s*[\"'])([^\"'\r\n]+)"),
    ("<COOKIE>", r"(?i)(\bcurl\b[^|;\n]*?\s(?:-b|--cookie)\s+[\"']?)([^\"'\s]+)"),
    ("<TOKEN>", r"(?i)(\bx-(?:api-key|auth-token|access-token)\b\s*[:=]\s*[\"']?)([^\s\"',;}]+)"),
    # URLs with embedded credentials and connection strings.
    ("<PASSWORD>", r"(?i)(\b[a-z][a-z0-9+.\-]*://[^\s:/@\"']+:)([^\s@/\"']+)(@)"),
    ("<PASSWORD>", r"(?i)((?:^|[;\s])(?:password|pwd)=(?!=))([^;\"'\s]+)"),
    ("<SECRET>", r"(?i)((?:\bAccountKey|\bSharedAccessKey|[?&;]sig)=(?!=))([^;&\"'\s]+)"),
    # Query-string secrets.
    ("<SECRET>", r"(?i)([?&](?:" + _KEYWORDS + r"|key|code|sig|signature)=(?!=))([^&\s\"'#]+)"),
    # CLI flags: --password x, --token=x, -Token "x".
    ("<SECRET>", r"(?i)((?:^|\s)--?" + _KEYWORDS + r"(?:[=:]|\s+)[\"']?)([^\s\"']{3,})"),
    ("<PASSWORD>", r"(?i)(\b(?:mysql|mysqldump|mariadb)\b[^|;&\n]*?\s-p)([^\s\"'-][^\s\"']{3,})"),
    # Env assignments: export X_TOKEN=..., $env:X_KEY = "...", set X_SECRET=..., "x_password": "..."
    ("<SECRET>", r"(?i)(\$env:[A-Za-z0-9_]*" + _KEYWORDS + r"[A-Za-z0-9_]*\s*=(?!=)\s*[\"']?)([^\"'\s;]+)"),
    ("<SECRET>", r"(?i)(\b(?:export\s+|set\s+|setx\s+)?[A-Za-z0-9_]*" + _KEYWORDS + r"[A-Za-z0-9_]*\s*=(?!=)\s*[\"']?)([^\"'\s;&|,)]{4,})"),
    ("<SECRET>", r"(?i)([\"']?[A-Za-z0-9_\-]*" + _KEYWORDS + r"[A-Za-z0-9_\-]*[\"']?\s*:\s*[\"'])([^\"']{4,})([\"'])"),
    ("<PASSWORD>", r"(?i)(ConvertTo-SecureString\s+(?:-String\s+)?[\"'])([^\"']+)([\"'])"),
]

_COMPILED_VENDOR = [(ph, re.compile(p)) for ph, p in _VENDOR]
_COMPILED_CONTEXT = [(ph, re.compile(p)) for ph, p in _CONTEXT]
_PLACEHOLDER = re.compile(r"^<[A-Z_]+>$")
_VARIABLE = re.compile(r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_:.]*\}?|%[A-Za-z_]+%|\$\(.*|<[A-Z_]+>)$")
# Unquoted code expressions (attribute access, calls, literals) are references, not secret values.
_CODE = re.compile(r"^(?:[A-Za-z_]\w*(?:\??\.[A-Za-z_]\w*)+|.*[()\[\]{}].*|true|false|null|none|undefined|\d{1,6}|if)$", re.I)
_HIGH_ENTROPY = re.compile(r"(?<![A-Za-z0-9/+_\-])(?=[A-Za-z0-9+/_\-]*[0-9])(?=[A-Za-z0-9+/_\-]*[a-z])(?=[A-Za-z0-9+/_\-]*[A-Z])[A-Za-z0-9+/_\-]{40,}={0,2}(?![A-Za-z0-9/+_\-])")
_HEXISH = re.compile(r"^[0-9a-fA-F]+$")


def _keep_value(value: str) -> bool:
    """Variable references, code expressions and existing placeholders are not secrets."""
    value = value.rstrip("\\\"'")
    return bool(_VARIABLE.match(value) or _PLACEHOLDER.match(value) or _CODE.match(value))


def _benign_token(token: str) -> bool:
    """Hex digests, paths and word-built slugs look random but are not secrets."""
    if _HEXISH.match(token) or token.count("/") > 2:
        return True
    if sum(1 for w in re.split(r"[-_/.]", token) if len(w) >= 4 and w.isalpha()) >= 2:
        return True
    counts = [token.count(c) for c in set(token)]
    return -sum(n / len(token) * math.log2(n / len(token)) for n in counts) < 4.3


def redact(text: str | None) -> str | None:
    if not text:
        return text
    out = text
    for ph, rx in _COMPILED_VENDOR:
        out = rx.sub(ph, out)

    for ph, rx in _COMPILED_CONTEXT:
        def repl(m: re.Match, ph=ph) -> str:
            groups = m.groups()
            if _keep_value(groups[1]):
                return m.group(0)
            return groups[0] + ph + (groups[2] if len(groups) > 2 and groups[2] else "")
        out = rx.sub(repl, out)
    return _HIGH_ENTROPY.sub(lambda m: m.group(0) if _benign_token(m.group(0)) else "<SECRET>", out)


def find_secrets(text: str | None) -> list[str]:
    """Spans redact() would replace; empty for already-redacted text."""
    if not text:
        return []
    hits: list[str] = []
    for _, rx in _COMPILED_VENDOR:
        hits += [m.group(0) for m in rx.finditer(text)]
    for _, rx in _COMPILED_CONTEXT:
        hits += [m.groups()[1] for m in rx.finditer(text) if not _keep_value(m.groups()[1])]
    hits += [m.group(0) for m in _HIGH_ENTROPY.finditer(text) if not _benign_token(m.group(0))]
    return hits


def leaks(output: str, raw_command: str) -> list[str]:
    """Secret substrings of the raw command that appear in the output, plus secret-shaped output."""
    found = []
    for secret in set(find_secrets(raw_command)):
        s = secret.strip("\"' ")
        if len(s) >= 4 and s in output:
            found.append(s)
    return found + find_secrets(output)
