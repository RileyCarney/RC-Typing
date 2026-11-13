"""Command-line interface for rctyping-app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn
import httpx

from rctyping_app.config import settings
from rctyping_app.core.keystore import KeyStore
from rctyping_common.certificate import (
    public_key_from_pem,
    verify_certificate_envelope,
)
from rctyping_common.models import CertificateEnvelope


def cmd_serve(args: argparse.Namespace) -> None:
    """Run the web application server."""
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"Starting rc-typing server at http://{host}:{port}")
    uvicorn.run("rctyping_app.main:app", host=host, port=port, reload=args.reload)


def cmd_pubkey(args: argparse.Namespace) -> None:
    """Display the issuer public key."""
    keys_dir = settings.data_dir / "keys"
    keystore = KeyStore(keys_dir=keys_dir, passphrase=settings.key_passphrase)
    print("=== rc-typing Issuer Public Key ===")
    print(f"Key ID (Fingerprint): {keystore.key_id}")
    print(f"Raw Base64URL:        {keystore.get_public_key_b64()}")
    print("\nPEM format:")
    print(keystore.get_public_key_pem())


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify a certificate file offline or via registry."""
    cert_path = Path(args.certificate_file)
    if not cert_path.exists():
        print(f"Error: Certificate file '{cert_path}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(cert_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        envelope = CertificateEnvelope(**data)
    except Exception as e:
        print(f"Error reading/parsing certificate: {e}", file=sys.stderr)
        sys.exit(1)

    expected_pub = None
    if args.pubkey:
        with open(args.pubkey, "r", encoding="utf-8") as f:
            expected_pub = public_key_from_pem(f.read())

    # 1. Offline cryptographic verification
    valid = verify_certificate_envelope(envelope, expected_public_key=expected_pub)
    p = envelope.payload
    print("=" * 60)
    print(f"CERTIFICATE VERIFICATION REPORT: {p.cert_id}")
    print("=" * 60)
    print(f"Subject:             {p.subject}")
    print(f"Category:            {p.category}" + (f" ({p.language})" if p.language else ""))
    print(f"Net Speed:           {p.metrics.net_wpm} WPM")
    print(f"Raw Speed:           {p.metrics.raw_wpm} WPM")
    print(f"Accuracy:            {p.metrics.accuracy * 100:.1f}%")
    print(f"Consistency:         {p.metrics.consistency * 100:.0f}%")
    print(f"Duration:            {p.metrics.duration_ms / 1000:.1f}s")
    print(f"Issued At:           {p.issued_at}")
    print(f"Issuer Key ID:       {p.issuer_id}")
    print(f"Integrity Status:    {p.integrity}")
    print(f"Assurance Level:     {p.assurance}")
    print("-" * 60)

    if not valid:
        print("[!] SIGNATURE VERIFICATION FAILED: TAMPERED OR INVALID SIGNATURE")
        sys.exit(2)

    print("[OK] Cryptographic Ed25519 signature is VALID over canonical payload.")

    # 2. Optional registry check
    reg_url = args.registry or settings.registry_url
    if reg_url:
        print(f"\nChecking public registry at {reg_url}...")
        try:
            resp = httpx.get(f"{reg_url}/v1/certificates/{p.cert_id}", timeout=5.0)
            if resp.status_code == 200:
                reg_data = resp.json()
                print(f"[OK] Certificate is recorded in transparency log at leaf index {reg_data.get('leaf_index')}.")
                print(f"     Issuer trust tier: {reg_data.get('trust_tier', 'unverified')}")
                if reg_data.get("is_revoked"):
                    print("     [!] WARNING: This certificate has been REVOKED.")
            elif resp.status_code == 404:
                print("     [Note] Certificate is valid offline, but not published in this registry.")
            else:
                print(f"     [Note] Registry returned HTTP {resp.status_code}.")
        except Exception as e:
            print(f"     [Note] Could not reach registry ({e}).")

    print("\nDisclaimer: Subject display name is self-asserted and unverified.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="rctyping-app", description="rc-typing CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = subparsers.add_parser("serve", help="Start FastAPI web server")
    p_serve.add_argument("--host", default=None, help="Host to bind to")
    p_serve.add_argument("--port", type=int, default=None, help="Port to listen on")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload")
    p_serve.set_defaults(func=cmd_serve)

    # pubkey
    p_pubkey = subparsers.add_parser("pubkey", help="Show issuer public key")
    p_pubkey.set_defaults(func=cmd_pubkey)

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify a certificate JSON file")
    p_verify.add_argument("certificate_file", help="Path to certificate JSON file")
    p_verify.add_argument("--pubkey", help="Optional path to expected public key PEM file")
    p_verify.add_argument("--registry", help="Optional registry URL to check inclusion proof")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
