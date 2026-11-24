"""nock's hosted docs, as `POST /docs` keeps them and `GET /docs/{cli}` serves them: a bundle is a signed
manifest (format, version, the oldest nock it is for, a SHA-256 per file) and the files, built by nock's
`scripts/publish_docs.py` and verified by nock itself before it shows them (`src/nock/hosted.py`). The
signature is the only credential a publish needs: what the makers' private key signed is kept."""

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from nock_api.rules import Refused

FORMAT = 1
# The public half of the key nock's docs are signed with, which nock builds in too.
PUBLIC_KEY = "JJ8L2q+aI7j4FoC4NVZSmuSKUSs1by2G6Efqpg3ALTA="
SEMANTIC = re.compile(r"\d{1,6}\.\d{1,6}\.\d{1,6}")
# The largest bundle read: nock's docs are about 120 KB.
LARGEST = 1_000_000


@dataclass(frozen=True)
class Bundle:
    min_cli: str
    version: int
    text: str


def release(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def key(text: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(text, validate=True))


def bundle(sent: Any, public: Ed25519PublicKey) -> Bundle:
    """The bundle sent, when it is whole and signed with `public`; else `Refused`."""
    if not isinstance(sent, dict) or set(sent) != {"manifest", "signature", "docs"}:
        raise Refused("a bundle is exactly manifest, signature and docs", "shape")
    manifest, signature, texts = sent["manifest"], sent["signature"], sent["docs"]
    if not (isinstance(manifest, str) and isinstance(signature, str) and isinstance(texts, dict)):
        raise Refused("manifest and signature are strings, docs an object", "shape")
    try:
        public.verify(base64.b64decode(signature, validate=True), manifest.encode())
    except (InvalidSignature, binascii.Error, ValueError) as error:
        raise Refused("the signature does not verify with nock's docs key", "signature") from error
    said = json.loads(manifest)
    if not isinstance(said, dict) or said.get("format") != FORMAT:
        raise Refused(f"the manifest's format is not {FORMAT}", "format")
    version, min_cli, hashes = said.get("version"), said.get("min_cli"), said.get("docs")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise Refused("the manifest's version is a whole number of at least 0", "version")
    if not isinstance(min_cli, str) or not SEMANTIC.fullmatch(min_cli):
        raise Refused("the manifest's min_cli is MAJOR.MINOR.PATCH", "version")
    if not isinstance(hashes, dict) or set(hashes) != set(texts):
        raise Refused("the docs are not the files the manifest lists", "docs")
    for path, text in texts.items():
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != hashes[path]:
            raise Refused("a file does not match its hash in the manifest", "docs")
    return Bundle(min_cli, version, json.dumps(sent, separators=(",", ":")))
