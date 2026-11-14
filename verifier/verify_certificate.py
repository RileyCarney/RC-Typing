#!/usr/bin/env python3
"""Standalone certificate verifier for rc-typing.

Zero-app dependency script. Requires only standard library + `cryptography`.
Can be given to third parties to independently verify certificates.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sys
from typing import Any, List, Optional
import urllib.request
import urllib.error

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:
    print("Error: 'cryptography' library required. Install with: pip install cryptography", file=sys.stderr)
    sys.exit(1)


def _normalize_item(item: Any) -> Any:
    if item is None or isinstance(item, (bool, int, str)):
        return item
    if isinstance(item, float):
        if math.isnan(item) or math.isinf(item):
            raise ValueError(f"Non-finite float not allowed: {item}")
        return int(item) if item.is_integer() else round(item, 10)
    if isinstance(item, (list, tuple)):
        return [_normalize_item(x) for x in item]
    if isinstance(item, dict):
        return {str(k): _normalize_item(v) for k, v in sorted(item.items(), key=lambda kv: str(kv[0]))}
    raise TypeError(f"Unsupported type: {type(item)}")


def canonical_json_dumps(data: Any) -> bytes:
    normalized = _normalize_item(data)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def b64url_decode(data: str) -> bytes:
    padding = len(data) % 4
    if padding:
        data += "=" * (4 - padding)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def leaf_hash(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def verify_merkle_inclusion(leaf_data: bytes, leaf_index: int, tree_size: int, audit_path: List[str], expected_root_hex: str) -> bool:
    if not (0 <= leaf_index < tree_size):
        return False
    if tree_size == 1:
        return len(audit_path) == 0 and leaf_hash(leaf_data).hex().lower() == expected_root_hex.lower()

    fn = leaf_index
    sn = tree_size - 1
    r0 = leaf_hash(leaf_data)

    for p in audit_path:
        sibling = bytes.fromhex(p)
        if sn == 0:
            return False
        if (fn & 1) or (fn == sn):
            r0 = node_hash(sibling, r0)
            while not (fn & 1) and (fn != 0):
                fn >>= 1
                sn >>= 1
        else:
            r0 = node_hash(r0, sibling)
        fn >>= 1
        sn >>= 1

    return sn == 0 and r0.hex().lower() == expected_root_hex.lower()


def verify_certificate(cert_path: str, pubkey_path: Optional[str] = None, registry_url: Optional[str] = None) -> bool:
    with open(cert_path, "r", encoding="utf-8") as f:
        envelope = json.load(f)

    payload = envelope.get("payload", {})
    sig_b64 = envelope.get("signature", "")
    pub_str = envelope.get("issuer_public_key", "")

    # Parse public key
    if pubkey_path:
        with open(pubkey_path, "r", encoding="utf-8") as f:
            pub_data = f.read()
        pub = serialization.load_pem_public_key(pub_data.encode("utf-8"))
    else:
        if pub_str.startswith("-----BEGIN"):
            pub = serialization.load_pem_public_key(pub_str.encode("utf-8"))
        else:
            raw_pub = b64url_decode(pub_str)
            pub = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub)

    # 1. Check Issuer ID fingerprint
    raw_bytes = pub.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    computed_key_id = hashlib.sha256(raw_bytes).hexdigest()
    if payload.get("issuer_id") != computed_key_id:
        print("[FAIL] Issuer ID does not match public key fingerprint!", file=sys.stderr)
        return False

    # 2. Verify Ed25519 signature over canonical JSON
    canonical_bytes = canonical_json_dumps(payload)
    sig_bytes = b64url_decode(sig_b64)
    try:
        pub.verify(sig_bytes, canonical_bytes)
    except InvalidSignature:
        print("[FAIL] Cryptographic signature is INVALID or payload has been tampered with!", file=sys.stderr)
        return False

    m = payload.get("metrics", {})
    print("=" * 65)
    print(f"VERIFIED RC-TYPING CERTIFICATE: {payload.get('cert_id')}")
    print("=" * 65)
    print(f"Subject Name:        {payload.get('subject')} (User-asserted)")
    print(f"Category:            {payload.get('category')}" + (f" ({payload.get('language')})" if payload.get("language") else ""))
    print(f"Net Speed:           {m.get('net_wpm')} WPM")
    print(f"Raw Speed:           {m.get('raw_wpm')} WPM")
    print(f"Accuracy:            {float(m.get('accuracy', 0)) * 100:.1f}%")
    print(f"Consistency:         {float(m.get('consistency', 0)) * 100:.0f}%")
    print(f"Duration:            {float(m.get('duration_ms', 0)) / 1000:.1f}s")
    print(f"Integrity Status:    {payload.get('integrity')}")
    print(f"Assurance:           {payload.get('assurance')}")
    print(f"Issued At:           {payload.get('issued_at')}")
    print(f"Issuer Key ID:       {payload.get('issuer_id')}")
    print("-" * 65)
    print("[OK] Cryptographic signature verified successfully.")

    # 3. Query public registry if requested
    if registry_url:
        cert_id = payload.get("cert_id")
        url = f"{registry_url.rstrip('/')}/v1/certificates/{cert_id}"
        print(f"\nChecking public transparency registry at {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rctyping-standalone-verifier"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                reg_data = json.loads(resp.read().decode("utf-8"))
                print(f"[OK] Record found in transparency log at leaf index {reg_data.get('leaf_index')}.")
                print(f"     Issuer trust tier: {reg_data.get('trust_tier')}")

                local_envelope_bytes = canonical_json_dumps(envelope)
                reg_envelope_bytes = canonical_json_dumps(reg_data.get("envelope", {}))
                if reg_envelope_bytes != local_envelope_bytes:
                    print("[FAIL] Registry envelope does not match local certificate.", file=sys.stderr)
                    return False

                proof = reg_data.get("inclusion_proof", {})
                head = reg_data.get("signed_tree_head", {})
                if not proof or not head:
                    print("[FAIL] Registry response missing inclusion proof or signed tree head.", file=sys.stderr)
                    return False

                inc_valid = verify_merkle_inclusion(
                    leaf_data=local_envelope_bytes,
                    leaf_index=proof["leaf_index"],
                    tree_size=proof["tree_size"],
                    audit_path=proof["audit_path"],
                    expected_root_hex=head["root_hash"],
                )
                if not inc_valid:
                    print("[FAIL] RFC 6962 Merkle inclusion proof FAILED.", file=sys.stderr)
                    return False
                print("     [OK] RFC 6962 Merkle inclusion proof verified against signed tree root.")

                if reg_data.get("is_revoked"):
                    print(
                        f"[FAIL] This certificate was REVOKED: {reg_data.get('revocation_reason')}",
                        file=sys.stderr,
                    )
                    return False
        except urllib.error.HTTPError as err:
            if err.code == 404:
                print(f"     [Note] Certificate valid offline, but not present in this registry.")
            else:
                print(f"     [Error] Registry returned HTTP {err.code}.")
        except Exception as e:
            print(f"     [Note] Could not connect to registry: {e}")

    print("\nDisclaimer: Display name is user-provided and unverified.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Independently verify rc-typing certificate JSON")
    parser.add_argument("certificate_file", help="Path to certificate .json file")
    parser.add_argument("--pubkey", help="Optional path to issuer public key PEM")
    parser.add_argument("--registry", help="Optional URL of rc-typing public registry to check inclusion proof")

    args = parser.parse_args()
    success = verify_certificate(args.certificate_file, args.pubkey, args.registry)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
