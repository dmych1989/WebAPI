# -*- coding: utf-8 -*-
"""
DeepSeekHashV1 — Pure Python Implementation

Ported from Go: github.com/l-spaces/deepseek-api/pow/deepseek_hash.go

DeepSeekHashV1 = SHA3-256 but Keccak-f[1600] skips round 0 (only rounds 1..23).
- rate  = 136 bytes (1088 bits)
- pad   = 0x06 + 0x80  (standard SHA-3 padding)
- out   = 32 bytes (256 bits)
- rounds = 1..23 (23 rounds, NOT standard 24)

This makes the output COMPLETELY incompatible with standard SHA3-256.
"""

from __future__ import annotations

import struct
from typing import List

# Keccak-f[1600] round constants (24 total, we use rc[1]..rc[23])
_RC: List[int] = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

_MASK64 = 0xFFFFFFFFFFFFFFFF


def _rotl64(v: int, k: int) -> int:
    """64-bit rotate left"""
    return ((v << k) | (v >> (64 - k))) & _MASK64


def _keccak_f23(state: List[int]) -> None:
    """
    Keccak-f[1600] permutation — 23 rounds (skipping round 0).

    Operates in-place on a list of 25 uint64 values.
    Direct translation from Go's unrolled keccakF23.
    """
    a0, a1, a2, a3, a4 = state[0], state[1], state[2], state[3], state[4]
    a5, a6, a7, a8, a9 = state[5], state[6], state[7], state[8], state[9]
    a10, a11, a12, a13, a14 = state[10], state[11], state[12], state[13], state[14]
    a15, a16, a17, a18, a19 = state[15], state[16], state[17], state[18], state[19]
    a20, a21, a22, a23, a24 = state[20], state[21], state[22], state[23], state[24]

    for r in range(1, 24):
        # θ (theta)
        c0 = a0 ^ a5 ^ a10 ^ a15 ^ a20
        c1 = a1 ^ a6 ^ a11 ^ a16 ^ a21
        c2 = a2 ^ a7 ^ a12 ^ a17 ^ a22
        c3 = a3 ^ a8 ^ a13 ^ a18 ^ a23
        c4 = a4 ^ a9 ^ a14 ^ a19 ^ a24
        d0 = c4 ^ _rotl64(c1, 1)
        d1 = c0 ^ _rotl64(c2, 1)
        d2 = c1 ^ _rotl64(c3, 1)
        d3 = c2 ^ _rotl64(c4, 1)
        d4 = c3 ^ _rotl64(c0, 1)

        a0 ^= d0;  a5 ^= d0;  a10 ^= d0; a15 ^= d0; a20 ^= d0
        a1 ^= d1;  a6 ^= d1;  a11 ^= d1; a16 ^= d1; a21 ^= d1
        a2 ^= d2;  a7 ^= d2;  a12 ^= d2; a17 ^= d2; a22 ^= d2
        a3 ^= d3;  a8 ^= d3;  a13 ^= d3; a18 ^= d3; a23 ^= d3
        a4 ^= d4;  a9 ^= d4;  a14 ^= d4; a19 ^= d4; a24 ^= d4

        # ρ (rho) + π (pi)
        b0  = a0
        b10 = _rotl64(a1, 1)
        b20 = _rotl64(a2, 62)
        b5  = _rotl64(a3, 28)
        b15 = _rotl64(a4, 27)
        b16 = _rotl64(a5, 36)
        b1  = _rotl64(a6, 44)
        b11 = _rotl64(a7, 6)
        b21 = _rotl64(a8, 55)
        b6  = _rotl64(a9, 20)
        b7  = _rotl64(a10, 3)
        b17 = _rotl64(a11, 10)
        b2  = _rotl64(a12, 43)
        b12 = _rotl64(a13, 25)
        b22 = _rotl64(a14, 39)
        b23 = _rotl64(a15, 41)
        b8  = _rotl64(a16, 45)
        b18 = _rotl64(a17, 15)
        b3  = _rotl64(a18, 21)
        b13 = _rotl64(a19, 8)
        b14 = _rotl64(a20, 18)
        b24 = _rotl64(a21, 2)
        b9  = _rotl64(a22, 61)
        b19 = _rotl64(a23, 56)
        b4  = _rotl64(a24, 14)

        # χ (chi)
        a0  = b0  ^ (~b1  & b2)
        a1  = b1  ^ (~b2  & b3)
        a2  = b2  ^ (~b3  & b4)
        a3  = b3  ^ (~b4  & b0)
        a4  = b4  ^ (~b0  & b1)
        a5  = b5  ^ (~b6  & b7)
        a6  = b6  ^ (~b7  & b8)
        a7  = b7  ^ (~b8  & b9)
        a8  = b8  ^ (~b9  & b5)
        a9  = b9  ^ (~b5  & b6)
        a10 = b10 ^ (~b11 & b12)
        a11 = b11 ^ (~b12 & b13)
        a12 = b12 ^ (~b13 & b14)
        a13 = b13 ^ (~b14 & b10)
        a14 = b14 ^ (~b10 & b11)
        a15 = b15 ^ (~b16 & b17)
        a16 = b16 ^ (~b17 & b18)
        a17 = b17 ^ (~b18 & b19)
        a18 = b18 ^ (~b19 & b15)
        a19 = b19 ^ (~b15 & b16)
        a20 = b20 ^ (~b21 & b22)
        a21 = b21 ^ (~b22 & b23)
        a22 = b22 ^ (~b23 & b24)
        a23 = b23 ^ (~b24 & b20)
        a24 = b24 ^ (~b20 & b21)

        # ι (iota)
        a0 ^= _RC[r]

    state[0]  = a0  & _MASK64
    state[1]  = a1  & _MASK64
    state[2]  = a2  & _MASK64
    state[3]  = a3  & _MASK64
    state[4]  = a4  & _MASK64
    state[5]  = a5  & _MASK64
    state[6]  = a6  & _MASK64
    state[7]  = a7  & _MASK64
    state[8]  = a8  & _MASK64
    state[9]  = a9  & _MASK64
    state[10] = a10 & _MASK64
    state[11] = a11 & _MASK64
    state[12] = a12 & _MASK64
    state[13] = a13 & _MASK64
    state[14] = a14 & _MASK64
    state[15] = a15 & _MASK64
    state[16] = a16 & _MASK64
    state[17] = a17 & _MASK64
    state[18] = a18 & _MASK64
    state[19] = a19 & _MASK64
    state[20] = a20 & _MASK64
    state[21] = a21 & _MASK64
    state[22] = a22 & _MASK64
    state[23] = a23 & _MASK64
    state[24] = a24 & _MASK64


def deepseek_hash_v1(data: bytes) -> bytes:
    """
    DeepSeekHashV1 — returns 32-byte digest.

    Equivalent to WASM's wasm_deepseek_hash_v1.
    SHA3-256 structure but keccakF23 (23 rounds, skip round 0).
    """
    RATE = 136  # bytes

    state = [0] * 25

    # Absorb full blocks
    off = 0
    while off + RATE <= len(data):
        for i in range(RATE // 8):
            state[i] ^= struct.unpack_from("<Q", data, off + i * 8)[0]
        _keccak_f23(state)
        off += RATE

    # Padding
    final = bytearray(RATE)
    remaining = len(data) - off
    final[:remaining] = data[off:]
    final[remaining] = 0x06
    final[RATE - 1] |= 0x80

    for i in range(RATE // 8):
        state[i] ^= struct.unpack_from("<Q", bytes(final), i * 8)[0]
    _keccak_f23(state)

    # Squeeze: output = s[0]..s[3] in little-endian
    out = struct.pack("<4Q", state[0], state[1], state[2], state[3])
    return out


def solve_pow(challenge_hex: str, salt: str, expire_at: int, difficulty: int) -> int:
    """
    Search nonce in [0, difficulty) where DeepSeekHashV1(prefix + str(nonce)) == challenge.

    Optimized: pre-absorb the prefix into base_state, then only compute
    the tail part per iteration.

    Args:
        challenge_hex: 64-char hex string (32 bytes) — the target hash
        salt:           salt from the challenge
        expire_at:      expiration timestamp
        difficulty:     search space upper bound (default 144000)

    Returns:
        The nonce (answer) that satisfies the challenge

    Raises:
        ValueError: if no solution found within difficulty
    """
    if len(challenge_hex) != 64:
        raise ValueError(f"challenge must be 64 hex chars, got {len(challenge_hex)}")

    # Decode target hash into 4 uint64 (little-endian)
    target_bytes = bytes.fromhex(challenge_hex)
    t0, t1, t2, t3 = struct.unpack("<4Q", target_bytes)

    # Build prefix: "salt_{expire_at}_"
    prefix = f"{salt}_{expire_at}_".encode("utf-8")

    RATE = 136

    # Pre-absorb prefix into base_state
    base_state = [0] * 25
    off = 0
    while off + RATE <= len(prefix):
        for i in range(RATE // 8):
            base_state[i] ^= struct.unpack_from("<Q", prefix, off + i * 8)[0]
        _keccak_f23(base_state)
        off += RATE

    tail = prefix[off:]
    tail_len = len(tail)

    # Iterate through all possible nonces
    for n in range(difficulty):
        # Build the full remaining input: tail + str(n)
        nonce_str = str(n).encode("utf-8")
        total_tail = tail_len + len(nonce_str)

        # Copy base_state
        s = base_state[:]

        if total_tail < RATE:
            # Single final block
            buf = bytearray(RATE)
            buf[:tail_len] = tail
            buf[tail_len:tail_len + len(nonce_str)] = nonce_str
            buf[total_tail] = 0x06
            buf[RATE - 1] |= 0x80
            for i in range(RATE // 8):
                s[i] ^= struct.unpack_from("<Q", bytes(buf), i * 8)[0]
            _keccak_f23(s)
        else:
            # Two blocks: first partial + overflow
            first_block_remainder = RATE - tail_len
            buf1 = bytearray(RATE)
            buf1[:tail_len] = tail
            buf1[tail_len:RATE] = nonce_str[:first_block_remainder]
            for i in range(RATE // 8):
                s[i] ^= struct.unpack_from("<Q", bytes(buf1), i * 8)[0]
            _keccak_f23(s)

            rem = total_tail - RATE
            buf2 = bytearray(RATE)
            buf2[:rem] = nonce_str[first_block_remainder:]
            buf2[rem] = 0x06
            buf2[RATE - 1] |= 0x80
            for i in range(RATE // 8):
                s[i] ^= struct.unpack_from("<Q", bytes(buf2), i * 8)[0]
            _keccak_f23(s)

        # Check if hash matches target
        if s[0] == t0 and s[1] == t1 and s[2] == t2 and s[3] == t3:
            return n

    raise ValueError(f"DeepSeek POW: no solution found within difficulty={difficulty}")


def build_pow_header(
    algorithm: str,
    challenge: str,
    salt: str,
    answer: int,
    signature: str,
    target_path: str,
) -> str:
    """Build the x-ds-pow-response header value (base64-encoded JSON)."""
    import base64
    import json

    payload = {
        "algorithm": algorithm,
        "challenge": challenge,
        "salt": salt,
        "answer": answer,
        "signature": signature,
        "target_path": target_path,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()
