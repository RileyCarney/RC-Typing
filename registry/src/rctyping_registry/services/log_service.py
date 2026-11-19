"""Transparency log service backed by RFC 6962 Merkle tree and database."""

from __future__ import annotations

import datetime
import threading
from typing import Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from rctyping_common.canonical import canonical_json_dumps
from rctyping_common.certificate import b64url_encode
from rctyping_common.merkle import MerkleTree, leaf_hash
from rctyping_common.models import InclusionProof, SignedTreeHead
from rctyping_registry.core.registry_keystore import RegistryKeyStore
from rctyping_registry.db.models import LogEntryModel, TreeHeadModel


class LogService:

    def __init__(self, keystore: RegistryKeyStore) -> None:
        self.keystore = keystore
        self.tree = MerkleTree()
        self._lock = threading.RLock()

    @property
    def lock(self) -> threading.RLock:
        """Return the reentrant lock synchronizing transparency log mutations and reads."""
        return self._lock

    def sync_from_db(self, db: Session) -> None:
        """Load all existing log entry hashes in index order into in-memory tree."""
        with self._lock:
            entries = db.query(LogEntryModel.leaf_hash).order_by(LogEntryModel.leaf_index.asc()).all()
            self.tree = MerkleTree(leaf_hashes=[bytes.fromhex(e.leaf_hash) for e in entries])

    def append_certificate(
        self,
        cert_id: str,
        envelope_dict: dict[str, Any],
        db: Session,
        commit: bool = True,
    ) -> Tuple[int, int, InclusionProof, SignedTreeHead]:
        """Append certificate canonical JSON bytes to Merkle log, persist and sign tree head."""
        with self._lock:
            canonical_bytes = canonical_json_dumps(envelope_dict)
            prev_len = len(self.tree.leaf_hashes)
            try:
                leaf_idx = self.tree.append(canonical_bytes)
                l_hash = leaf_hash(canonical_bytes).hex()

                # 1. Save log entry
                log_entry = LogEntryModel(
                    leaf_index=leaf_idx,
                    cert_id=cert_id,
                    leaf_hash=l_hash,
                    data=canonical_bytes.decode("utf-8"),
                )
                db.add(log_entry)

                # 2. Compute tree head and sign
                tree_size = self.tree.size
                root_hex = self.tree.root_hex()
                now = datetime.datetime.now(datetime.timezone.utc)
                ts_str = now.isoformat()

                # Canonical signing format for tree head: "tree_size:root_hex:timestamp"
                head_canonical = f"{tree_size}:{root_hex}:{ts_str}".encode("utf-8")
                sig_bytes = self.keystore.private_key.sign(head_canonical)
                sig_b64 = b64url_encode(sig_bytes)

                signed_head = SignedTreeHead(
                    tree_size=tree_size,
                    root_hash=root_hex,
                    timestamp=ts_str,
                    signature=sig_b64,
                )

                db_head = TreeHeadModel(
                    tree_size=tree_size,
                    root_hash=root_hex,
                    timestamp=now,
                    signature=sig_b64,
                )
                db.add(db_head)
                if commit:
                    db.commit()

                # 3. Inclusion proof for this leaf
                audit_path = self.tree.get_inclusion_proof(leaf_idx)
                inclusion_proof = InclusionProof(
                    leaf_index=leaf_idx,
                    tree_size=tree_size,
                    audit_path=audit_path,
                )

                return leaf_idx, tree_size, inclusion_proof, signed_head
            except Exception:
                del self.tree.leaf_hashes[prev_len:]
                if commit:
                    db.rollback()
                raise

    def get_inclusion_proof(self, leaf_index: int) -> InclusionProof:
        with self._lock:
            if not (0 <= leaf_index < self.tree.size):
                raise IndexError(f"Leaf index {leaf_index} out of bounds")
            audit_path = self.tree.get_inclusion_proof(leaf_index)
            return InclusionProof(
                leaf_index=leaf_index,
                tree_size=self.tree.size,
                audit_path=audit_path,
            )

    def get_consistency_proof(self, prior_size: int) -> List[str]:
        with self._lock:
            if not (0 <= prior_size <= self.tree.size):
                raise IndexError(f"Prior size {prior_size} out of bounds")
            return self.tree.get_consistency_proof(prior_size)

    def get_latest_tree_head(self, db: Session) -> Optional[SignedTreeHead]:
        head = db.query(TreeHeadModel).order_by(TreeHeadModel.tree_size.desc()).first()
        if not head:
            return None
        ts = (
            head.timestamp
            if head.timestamp.tzinfo is not None
            else head.timestamp.replace(tzinfo=datetime.timezone.utc)
        )
        return SignedTreeHead(
            tree_size=head.tree_size,
            root_hash=head.root_hash,
            timestamp=ts.isoformat(),
            signature=head.signature,
        )
