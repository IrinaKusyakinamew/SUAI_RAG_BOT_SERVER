import json
import sys
import os
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance

# добавляем корневую директорию проекта в путь
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from rag_sources.minio_client import get_minio_client

# инициализация клиента Minio
minio_client = get_minio_client()

# путь к объекту в Minio 
jsonl_object_path1 = 'embeddings/all_chunks.jsonl'
jsonl_object_path2 = 'embeddings/schedules_chunks.jsonl'
bucket_name = 'rag-sources'

# две коллекции для документов и расписания
collection_name1 = 'text_embeddings'
collection_name2 = 'schedules_embeddings'

# клиент Qdrant
client = QdrantClient(
    url='http://212.192.220.24:6333',
    api_key='pii5z%cE1',
    timeout=120, # Таймаут для предотвращения разрыва соединения
    prefer_grpc=False # Используем REST вместо gRPC для стабильности
)

# ЗАПИХАЛИ В ФУНКЦИЮ
def to_qdrnt(bucket_name, jsonl_object_path, collection_name):
    collections = [col.name for col in client.get_collections().collections]
    if collection_name not in collections:
        print(f"Создаю коллекцию '{collection_name}'...")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE)
        )
        print(f"Коллекция '{collection_name}' успешно создана.")
    else:
        print(f"Коллекция '{collection_name}' уже существует.")

    response = minio_client.get_object(bucket_name, jsonl_object_path)

    points = []

    try:
        data = response.read().decode("utf-8")
        for line in data.splitlines():
            obj = json.loads(line)

            # ВАЖНО: мы НЕ пересобираем структуру
            point = {
                "id": obj["id"],
                "vector": obj["vector"],
                "payload": obj["payload"]
            }

            points.append(point)

    finally:
        response.close()

    batch_size = 100
    total_points = len(points)

    for i in range(0, total_points, batch_size):
        batch = points[i:i + batch_size]
        client.upsert(
            collection_name=collection_name,
            points=batch
        )
        print(f"Загружено {i + len(batch)} / {total_points}")

    print("Загрузка завершена.")


# вызываем функцию для каждого файла
to_qdrnt(bucket_name, jsonl_object_path1, collection_name1)
to_qdrnt(bucket_name, jsonl_object_path2, collection_name2)