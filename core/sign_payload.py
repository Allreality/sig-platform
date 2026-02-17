import hashlib, json, os, base64, secrets, requests
from datetime import datetime, timezone

SEV_SNP = "http://87.121.52.49"

def sign_payload(event_dict: dict) -> dict:
    payload_bytes = json.dumps(event_dict, sort_keys=True, separators=(",",":")).encode()
    payload_hash  = hashlib.sha256(payload_bytes).hexdigest()
    try:
        r = requests.post(f"{SEV_SNP}/attest",
            json={"payload_hash": payload_hash, "nonce": secrets.token_hex(16)},
            headers={"Authorization": f"Bearer {os.getenv('SEV_API_KEY','')}"},
            timeout=10)
        r.raise_for_status()
        d = r.json()
        return {"method":"sev-snp","payload_hash":payload_hash,
                "signature":d["signature"],"signed_at":_now()}
    except Exception:
        pass
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    key_path = os.getenv("SIG_KEY_PATH", "/var/sig/keys/private.pem")
    if not os.path.exists(key_path):
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        k = ec.generate_private_key(ec.SECP256K1())
        open(key_path,"wb").write(k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
    with open(key_path,"rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    sig = key.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))
    return {"method":"ecdsa-software","payload_hash":payload_hash,
            "signature":base64.b64encode(sig).decode(),"signed_at":_now(),
            "warning":"dev-only - upgrade to SEV-SNP for production"}

def _now(): return datetime.now(timezone.utc).isoformat()
