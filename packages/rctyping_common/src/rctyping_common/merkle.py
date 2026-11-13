"""RFC 6962 compliant Merkle Tree and Proofs.

Provides cryptographic append-only transparency log proofs:
- Leaf hash: SHA-256(0x00 || data)
- Interior node: SHA-256(0x01 || left || right)
- Inclusion proofs and consistency proofs.
"""

from __future__ import annotations

import hashlib
from typing import List, Sequence


def _largest_power_of_two_less_than(n: int) -> int:
    """Return the largest power of 2 strictly less than n (for n >= 2)."""
    if n < 2:
        return 0
    k = 1
    while (k << 1) < n:
        k <<= 1
    return k


def leaf_hash(data: bytes) -> bytes:
    """Compute RFC 6962 leaf hash: SHA-256(0x00 || data)."""
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    """Compute RFC 6962 interior node hash: SHA-256(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + left + right).digest()


class MerkleTree:
    """In-memory RFC 6962 Merkle Tree."""

    def __init__(self, leaves: Sequence[bytes] | None = None) -> None:
        self.raw_leaves: List[bytes] = list(leaves) if leaves else []
        self.leaf_hashes: List[bytes] = [leaf_hash(l) for l in self.raw_leaves]

    def append(self, data: bytes) -> int:
        """Append raw data leaf to tree, returns index of new leaf."""
        idx = len(self.raw_leaves)
        self.raw_leaves.append(data)
        self.leaf_hashes.append(leaf_hash(data))
        return idx

    @property
    def size(self) -> int:
        return len(self.leaf_hashes)

    def root_hash(self) -> bytes:
        """Compute the root hash of the tree."""
        if not self.leaf_hashes:
            return hashlib.sha256(b"").digest()
        return self._sub_root(0, len(self.leaf_hashes))

    def root_hex(self) -> str:
        return self.root_hash().hex()

    def _sub_root(self, start: int, end: int) -> bytes:
        n = end - start
        if n == 0:
            return hashlib.sha256(b"").digest()
        if n == 1:
            return self.leaf_hashes[start]
        k = _largest_power_of_two_less_than(n)
        left = self._sub_root(start, start + k)
        right = self._sub_root(start + k, end)
        return node_hash(left, right)

    def get_inclusion_proof(self, m: int) -> List[str]:
        """Generate audit path for leaf at index m (0 <= m < size).

        Returns list of hex-encoded sibling hashes.
        """
        n = len(self.leaf_hashes)
        if not (0 <= m < n):
            raise IndexError(f"Leaf index {m} out of bounds for tree size {n}")

        path_bytes = self._sub_path(m, 0, n)
        return [p.hex() for p in path_bytes]

    def _sub_path(self, m: int, start: int, end: int) -> List[bytes]:
        n = end - start
        if n <= 1:
            return []
        k = _largest_power_of_two_less_than(n)
        split = start + k
        if m < split:
            right_sub = self._sub_root(split, end)
            return self._sub_path(m, start, split) + [right_sub]
        else:
            left_sub = self._sub_root(start, split)
            return self._sub_path(m, split, end) + [left_sub]

    def get_consistency_proof(self, m: int) -> List[str]:
        """Generate consistency proof between tree size m and current tree size n (m <= n).

        RFC 6962 Section 2.1.2.
        """
        n = len(self.leaf_hashes)
        if not (0 <= m <= n):
            raise IndexError(f"Prior tree size {m} out of bounds for current size {n}")
        if m == 0 or m == n:
            return []

        path_bytes = self._sub_consistency(m, 0, n, True)
        return [p.hex() for p in path_bytes]

    def _sub_consistency(self, m: int, start: int, end: int, is_root: bool) -> List[bytes]:
        n = end - start
        if m == n:
            return [] if is_root else [self._sub_root(start, end)]
        k = _largest_power_of_two_less_than(n)
        split = start + k
        if m <= k:
            right = self._sub_root(split, end)
            return self._sub_consistency(m, start, split, is_root) + [right]
        else:
            left = self._sub_root(start, split)
            return self._sub_consistency(m - k, split, end, False) + [left]


def verify_inclusion_proof(
    leaf_data: bytes,
    leaf_index: int,
    tree_size: int,
    audit_path: Sequence[str | bytes],
    expected_root_hex: str,
) -> bool:
    """Verify that a leaf is included in the tree with the specified root hash per RFC 6962 Section 2.1.3."""
    if not (0 <= leaf_index < tree_size):
        return False
    if tree_size == 1:
        if len(audit_path) != 0:
            return False
        return leaf_hash(leaf_data).hex().lower() == expected_root_hex.lower()

    fn = leaf_index
    sn = tree_size - 1
    r0 = leaf_hash(leaf_data)

    for p in audit_path:
        sibling = bytes.fromhex(p) if isinstance(p, str) else p
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


def verify_consistency_proof(
    prior_size: int,
    current_size: int,
    prior_root_hex: str,
    current_root_hex: str,
    consistency_path: Sequence[str | bytes],
) -> bool:
    """Verify RFC 6962 Section 2.1.4 consistency proof."""
    if prior_size == 0:
        return True
    if prior_size == current_size:
        return prior_root_hex.lower() == current_root_hex.lower() and len(consistency_path) == 0
    if prior_size > current_size:
        return False

    path = [bytes.fromhex(p) if isinstance(p, str) else p for p in consistency_path]
    if not path:
        return False

    fn = prior_size - 1
    sn = current_size - 1

    while (fn & 1) != 0:
        fn >>= 1
        sn >>= 1

    path_idx = 0
    if fn == 0:
        fr = bytes.fromhex(prior_root_hex)
        sr = bytes.fromhex(prior_root_hex)
    else:
        fr = path[path_idx]
        sr = path[path_idx]
        path_idx += 1

    for c in path[path_idx:]:
        if sn == 0:
            return False
        if (fn & 1) or (fn == sn):
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            while not (fn & 1) and (fn != 0):
                fn >>= 1
                sn >>= 1
        else:
            sr = node_hash(sr, c)
        fn >>= 1
        sn >>= 1

    return sn == 0 and fr.hex().lower() == prior_root_hex.lower() and sr.hex().lower() == current_root_hex.lower()
