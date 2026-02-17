import hashlib, json, os, boto3

def store_offchain(payload_bytes: bytes, metadata: dict = {}) -> str:
    content_hash = hashlib.sha256(payload_bytes).hexdigest()
    filename     = f"sig/{content_hash}.json"
    bucket = os.getenv("S3_BUCKET")
    if bucket:
        s3 = boto3.client("s3",
            aws_access_key_id     = os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name           = os.getenv("AWS_REGION", "us-east-1"))
        s3.put_object(Bucket=bucket, Key=filename, Body=payload_bytes,
                      ContentType="application/json",
                      Metadata={k: str(v) for k, v in metadata.items()})
        return f"s3://{bucket}/{filename}"
    try:
        import ipfshttpclient
        client = ipfshttpclient.connect("/ip4/127.0.0.1/tcp/5001")
        return f"ipfs://{client.add_bytes(payload_bytes)}"
    except Exception:
        pass
    path = f"/var/sig/offchain/{filename}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(payload_bytes)
    return f"file://{path}"
