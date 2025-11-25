from minio import Minio
# Импортируем конфиг Minio из settings.py
from parser.out_spider.settings import MINIO_CONFIG

# Создание клиента Minio из connection-параметров без bucket_name
def get_minio_client():
    return Minio(
        MINIO_CONFIG["endpoint"],
        access_key=MINIO_CONFIG["access_key"],
        secret_key=MINIO_CONFIG["secret_key"],
        secure=MINIO_CONFIG["secure"],
    )

# Создание бакета с проверкой его существования
def create_minio_bucket(bucket: str):
    client = get_minio_client()
    found = client.bucket_exists(bucket)
    if not found:
        client.make_bucket(bucket)
        print(f"[MinIO] Bucket '{bucket}' создан")
    else:
        print(f"[MinIO] Bucket '{bucket}' уже существует")
    return client
